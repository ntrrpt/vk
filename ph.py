#!/usr/bin/env python3
import time
import sys
import json
import datetime
import argparse
import re
import asyncio
import util
from loguru import logger as log
from tqdm import tqdm
from vk_api import VkApi
from vk_api.exceptions import AuthError
from pathlib import Path
from stopwatch import Stopwatch

login_info = ""  # access token or "login:pass"


def rqst_method(method, values={}):
    while True:
        try:
            return vk.method(method, values)
        except Exception as ex:
            ex_str = str(ex)

            # invalid login/pass
            if "[5]" in ex_str:
                log.error("autechre error: " + ex_str[31:])
                sys.exit()

            # invalid id / no albums in group
            elif re.findall(r"\[100\]|\[113\]|group photos are disabled", ex_str):
                # log.trace(f"no id / no albums: {values}, {str(ex)}")
                return None

            # no access to albums
            elif re.findall(r"\[18\]|\[30\]|\[15\]|\[200\]", ex_str):
                # log.error(f"no access: {values}, {str(ex)}")
                return False

            # idk
            elif "server" in ex_str:
                log.error("internal catched, waiting...   ")
                time.sleep(60)

            else:
                log.error(f"{method!r}: {ex_str}")
                time.sleep(5)


def rqst_size(data: dict) -> str:
    priority = {"s": 1, "m": 2, "x": 3, "y": 4, "z": 5, "w": 6}
    return max(
        data.get("sizes", []),
        key=lambda s: priority.get(s["type"], 0),
        default={},
    ).get("url", "")

    """
    rip v5.67
    for j in [2560, 1280, 807, 604, 130, 75]:
        if f'photo_{j}' in json['response']['items'][i]:
            dict_append(json['response']['items'][i][f'photo_{j}'], text, date)
            break
    """


def get_album(t_info, t_path, input_str):
    sw = Stopwatch(2)
    sw.restart()

    img_dict = []

    album_name = "album" + input_str
    owner_id, album_id = input_str.split("_")

    match album_id:
        case "0":
            album_id = "profile"
            title = "Фотографии со страницы "
        case "00":
            album_id = "wall"
            title = "Фотографии на стене "
        case "000":
            album_id = "saved"
            title = "Сохранённые фотографии "
        case "-9000":
            album_id = "tagged"
            title = "Фотографии с отметками "
        case _:
            title = ""

    if owner_id.startswith("-"):
        title += f"сообщества {t_info['name']}"
    else:
        title += f"{t_info['first_name']} {t_info['last_name']}"

    album = rqst_method(
        "photos.getAlbums",
        {"owner_id": owner_id, "album_ids": album_id, "need_system": 0},
    )

    if owner_id.startswith("-") and album is None:
        title = t_info["name"]
    elif album_id not in ("wall", "profile", "saved", "tagged"):
        if "title" in album["items"][0]:
            title = album["items"][0]["title"]

    photos = rqst_method(
        "photos.getUserPhotos" if album_id == "tagged" else "photos.get",
        {
            "owner_id": owner_id,
            "album_id": album_id,
            "count": "1000",
            "extended": True,
            "rev": 0,
        },
    )

    count = photos["count"]
    if count == 0:
        log.warning("album is empty")
        return

    offset_count = count // 1000 + 1
    for i in range(offset_count):
        if i + 1 < offset_count:
            log.info(f" {i * 1000} / {count} ...")
            time.sleep(args.delay)

        photos = rqst_method(
            "photos.getUserPhotos" if album_id == "tagged" else "photos.get",
            {
                "owner_id": int(owner_id),
                "album_id": album_id,
                "offset": i * 1000,
                "count": "1000",
                "extended": True,
                "rev": 0,
            },
        )

        for i, item in enumerate(photos["items"]):
            url = rqst_size(item)
            if url:
                img_dict.append(
                    {
                        "index": len(img_dict),
                        "url": url,
                        "text": item.get("text") or None,
                        "date": item.get("date"),
                        "likes": item.get("likes", {}).get("count"),
                        "comments": item.get("comments", {}).get("count"),
                        "tags": item.get("tags", {}).get("count"),
                        "reposts": item.get("reposts", {}).get("count"),
                    }
                )
            else:
                log.warning(f"missing item {i}: {item}")

    # creating folders
    cwd = t_path / util.str_cut(f"{util.esc(title)} ({album_id})", 100)
    cwd.mkdir(parents=True, exist_ok=True)

    # album info
    if album_id not in ("wall", "profile", "saved", "tagged") and not album.get(
        "error"
    ):
        item = album["items"][0]

        description = (
            f"id: {item['id']}\n"
            f"thumb_id: {item['thumb_id']}\n"
            f"owner_id: {item['owner_id']}\n"
            f"title: {item['title']}\n"
            f"description: {item['description']}\n"
            f"created: {util.ts_fmt(item['created'])}\n"
            f"updated: {util.ts_fmt(item['updated'])}\n"
            f"saved: {util.dt_now()}\n"
            f"photos: {item['size']}"
        )

        util.write(cwd / f"{album_name}_description.txt", description)

    # saving json with images
    json_data = json.dumps(img_dict, indent=3, sort_keys=True, ensure_ascii=False)
    util.write(cwd / f"{album_name}_list.json", str(json_data))

    # start threads
    if args.simulate:
        return

    asyncio.run(util.dw_album(img_dict, cwd, concurrency=args.threads))

    log.success(f"{count} files in {datetime.timedelta(seconds=int(sw.duration))}")


def parse_link(i_work):
    # clean link
    i_work = (
        i_work.removeprefix("https://")
        .removeprefix("vk.com/")
        .removeprefix("public")
        .removeprefix("albums")
        .removesuffix("?rev=1")
        .removesuffix("?rev=0")
    )

    album_id = ""
    if i_work.startswith("album"):
        # dump one album 1/2
        i_work = i_work.removeprefix("album")
        i_work, album_id = i_work.split("_")

    i_work = util.str_toplus(i_work)

    # get target id
    check_group = rqst_method("groups.getById", {"group_ids": i_work})
    check_user = rqst_method("users.get", {"user_ids": i_work})

    # get target info
    if check_group and check_group[0]["name"] != "DELETED":
        t_info = check_group[0]
        t_work = util.str_tominus(t_info["id"])
        t_name = t_info["name"]
        t_path = Path() / f"{t_name} (-{t_info['id']})"
    elif check_user and not check_user[0].get("deactivated"):
        t_info = check_user[0]
        t_work = util.str_toplus(t_info["id"])
        t_name = t_info["first_name"] + " " + t_info["last_name"]
        t_path = Path() / f"{t_name} ({t_info['id']})"
    else:
        log.info("invalid url: " + i_work)
        return

    t_name = util.esc(t_name)

    # private page
    if t_info.get("is_closed"):
        if t_info.get("is_member") or t_info.get("can_access_closed"):
            pass
        else:
            log.error(f"{t_name} is closed")
            return

    # dump one album 2/2
    if album_id:
        get_album(t_info, Path(), t_work + "_" + album_id)
        return

    albums = rqst_method(
        "photos.getAlbums", {"owner_id": t_work, "album_ids": 0, "need_system": 1}
    )

    # no access to albums
    if not albums:
        log.error("no access to albums")
        return

    t_path.mkdir(parents=True, exist_ok=True)
    log.info(f"{i_work} => {t_path}")

    if albums is None:  # public detected
        log.warning("group photos disabled, downloading only wall photos")

        log.info("1 / 2 (profile)")
        get_album(t_info, t_path, f"{t_work}_0")

        log.info("2 / 2 (wall)")
        get_album(t_info, t_path, f"{t_work}_00")
    else:
        if "-" in t_work:
            log.info(f"0 / {len(albums['items'])} (wall)")
            get_album(t_info, t_path, f"{t_work}_00")

        for i, item in enumerate(albums["items"], start=1):
            if item["id"] == -6:
                log.info(f"{i} / {albums['count']} (profile)")
                get_album(t_info, t_path, f"{t_work}_0")

            elif item["id"] == -7:
                log.info(f"{i} / {albums['count']} (wall)")
                get_album(t_info, t_path, f"{t_work}_00")

            elif item["id"] == -15:
                log.info(f"{i} / {albums['count']} (saved)")
                get_album(t_info, t_path, f"{t_work}_000")

            elif item["id"] == -9000:
                log.info(f"{i} / {albums['count']} (tagged)")
                get_album(t_info, t_path, f"{t_work}_-9000")

            elif item["id"] == abs(item["id"]):
                log.info(f"{i} / {albums['count']} ({item['title']})")
                get_album(t_info, t_path, f"{t_work}_{item['id']}")

            else:
                log.critical(f"unexpected id: {item['id']}")

    print()


if __name__ == "__main__":
    # fmt: off
    ap = argparse.ArgumentParser()
    add = ap.add_argument

    add("-a", "--auth",     default=login_info,   help="Login info (token of login:pass)")
    add("-t", "--threads",  type=int, default=5,  help="Number of threads")
    add("-s", "--simulate", action="store_true",  help="Simulate (not download, only json with urls)")
    add("-d", "--delay",    type=int, default=15, help="Delay between chunks requests (in seconds)")
    add("-j", "--json",     action="store_true",  help="album.json parsing")
    add("-v", "--verbose",  action="store_true",  help="Verbose output")

    add("targets",          nargs="*",            help="users / groups to dump")

    args = ap.parse_args()
    # fmt: on

    log.remove()
    log.add(
        lambda msg: tqdm.write(msg, end=""),
        backtrace=True,
        diagnose=True,
        format="<level>[{time:HH:mm:ss}]</level> {message}",
        colorize=True,
        level="INFO",
    )

    if args.verbose:
        log.remove()
        log.add(lambda msg: tqdm.write(msg, end=""), colorize=True, level="TRACE")

    if args.json:
        current_dir = Path.cwd()

        def rqst_json(path):
            path = Path(path)

            with open(path) as file:
                try:
                    img_dict = json.load(file)
                except Exception as ex:
                    log.opt(exception=True).error(f"{path}: {str(ex)}")
                    return

            cwd = path.parent.resolve()
            if cwd == current_dir.resolve():
                cwd = Path() / path.stem
                cwd.mkdir(parents=True, exist_ok=True)
            log.info(cwd)

            sw = Stopwatch(2)
            sw.restart()

            asyncio.run(util.dw_album(img_dict, cwd, concurrency=args.threads))

            log.success(
                f"{len(img_dict)} files in {datetime.timedelta(seconds=int(sw.duration))}"
            )

        if args.targets:
            for t in args.targets:
                rqst_json(t)
            sys.exit()

        for file in Path(".").rglob("*.json"):
            if any(part.startswith(".") for part in file.parts):  # .venv
                continue

            rqst_json(file)

        sys.exit()

    if not args.auth:
        args.auth = f"{input('Login: ')}:{input('Pass: ')}"

    if len(args.auth) >= 85:
        vk = VkApi(token=args.auth, api_version="5.121")

    elif ":" in args.auth:
        lp = args.auth.split(":")
        vk = VkApi(lp[0], lp[1], app_id=2685278)
        while True:
            try:
                vk.auth()
                rqst_method("users.get")[0]["id"]  # auth test
                break
            except AuthError as ex:
                log.error("autechre error: " + str(ex))
                sys.exit()

    # from vk_api.utils import enable_debug_mode
    # enable_debug_mode(vk, print_content=True)

    if not args.targets:
        args.targets.append(f"id{rqst_method('users.get')[0]['id']}")

    for t in args.targets:
        parse_link(t)
