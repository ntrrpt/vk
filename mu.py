#!/usr/bin/env python3
import os
import sys
import requests
import time
import re
import math
import optparse
import ffmpeg
import concurrent.futures
from glob import glob

import util

from loguru import logger as log

from vk_api import VkApi
from vk_api import audio
from vk_api.exceptions import AuthError, AccessDenied

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

m3u8_threads = 3
skip_existing = True
ranges = []


def progress(string):
    print(" " * os.get_terminal_size().columns, end="\r")
    print(string, end="\r")


def rqst_method(method, values={}):
    while True:
        try:
            r = vk_session.method(method, values)
            return r

        except Exception as e:
            e = str(e)

            # invalid login/pass
            if "[5] User authorization failed:" in e:
                log.error("autechre error: " + e[31:])
                sys.exit()

            # non-existing user
            if "Invalid user id" in e:
                return None

            # non-existing group
            if "group_ids is undefined" in e:
                return None

            # non-existing chat
            if "no access to this chat" in e:
                return None

            # idk
            if "Internal server error" in e:
                log.warning("internal catched, waiting...   ")
                time.sleep(100)

            else:
                log.error(f"execption in '{method}': {e}, values={values}   ")
                time.sleep(10)


def rqst_multiple(track, final_name=""):
    # https://github.com/Zerogoki00/vk-audio-downloader
    def m3u8_block(block, key_url):
        def rqst_decryptor(u):
            k = util.get_with_retries(u, max_retries=50).content
            c = Cipher(
                algorithms.AES(k), modes.CBC(b"\x00" * 16), backend=default_backend()
            )

            return c.decryptor()

        segments = []
        segment_urls = re.findall(r"#EXTINF:\d+\.\d{3},\s(\S*)", block)

        for s_url in segment_urls:
            # base_url
            u = track["url"][: track["url"].rfind("/")] + "/" + s_url
            segments.append(util.get_with_retries(u).content)

        if "METHOD=AES-128" in block:
            segment_key_url = re.findall(r':METHOD=AES-128,URI="(\S*)"', block)[0]

            decryptor = rqst_decryptor(key_url)
            if segment_key_url != key_url:
                decryptor = rqst_decryptor(segment_key_url)

            for j, seg in enumerate(segments):
                segments[j] = decryptor.update(seg)

        return b"".join(segments)

    block_size = 1024  # 1 Kibibyte

    name = "%s - %s" % (
        util.str_cut(track["artist"], 100, ""),
        util.str_cut(track["title"], 100, ""),
    )

    desc = "%s - %s" % (
        util.str_cut(track["artist"], 50, ""),
        util.str_cut(track["title"], 50, ""),
    )

    if not final_name:
        final_name = "%s (%s).mp3" % (name, track["id"])
        final_name = util.escut(final_name, 0)  # ntfs escaping

    if skip_existing:
        glob_esc = {"[": "[[]", "]": "[]]"}
        glob_fn = "".join(glob_esc.get(c, c) for c in final_name)
        if glob("**/%s" % glob_fn, recursive=True):
            log.warning("exists | %s " % desc)
            return

    if ".mp3" in track["url"]:
        with requests.get(track["url"], stream=True, timeout=10) as r:
            if not r:
                log.error("%s: bad r (%s)" % (desc, r.status_code))
                return

            cl = int(r.headers.get("Content-Length", "0")) or None
            dw_total = 0
            with open("mu.ts", "wb", buffering=block_size) as file:
                for data in r.iter_content(chunk_size=block_size):
                    try:
                        file.write(data)
                        dw_total += len(data)

                        percent = (
                            math.ceil(cl / block_size)
                            / math.ceil(dw_total / block_size)
                        ) * 100

                        progress(
                            f"{desc}: {int(percent)}% {util.sizeof_fmt(cl)} / {util.sizeof_fmt(dw_total)}"
                        )

                    except Exception as e:
                        log.error("%s (%s)" % (os.path.basename(dir), str(e)))
                        time.sleep(5)

    elif ".m3u8" in track["url"]:
        r = util.get_with_retries(track["url"]).content
        if not r:
            log.error("rip response | %s" % track)
            return

        parts = r.decode("utf-8").split("#EXT-X-KEY")

        blocks = []
        for b in parts:
            if "#EXTINF" in b:
                blocks.append(b)

        if not blocks:
            log.error("internal | %s" % desc)
            return

        key_url = re.findall(r':METHOD=AES-128,URI="(\S*)"', blocks[0])[0]

        # https://stackoverflow.com/a/63514035
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=m3u8_threads
        ) as executor:
            future_to_blk = {
                executor.submit(m3u8_block, blk, key_url): (i, blk)
                for i, blk in enumerate(blocks)
            }
            futures = {}

            for future in concurrent.futures.as_completed(future_to_blk):
                i, blk = future_to_blk[future]
                futures[i] = blk, future

                percent = (len(futures) / (len(blocks))) * 100

                print(
                    f"{desc}: {int(percent)}% {len(blocks)} / {len(futures)}", end="\r"
                )

            for i, _ in enumerate(futures):
                blk, future = futures[i]
                try:
                    with open("frag%s.ts" % i, "wb") as file:
                        file.write(future.result())

                except Exception as e:
                    log.error("%r ex: %s" % (blk, e))

        # merging *.ts files in one
        with open("mu.ts", "wb") as ts:
            for i, _ in enumerate(blocks):
                fn = "frag%s.ts" % i
                with open(fn, "rb") as frg:
                    ts.write(frg.read())

                util.delete_file(fn)
                print(f"{desc}: dd {i} / {len(blocks)}          ", end="\r")
    else:
        log.error("nani | %s" % track)
        return

    md = [
        f"TPE1={track['artist']}",
        f"TIT2={track['title']}",
        f"COMM={track['owner_id']}_{track['id']}",
    ]
    md = {f"metadata:g:{i}": e for i, e in enumerate(md)}

    inputs = [ffmpeg.input("mu.ts")]

    # add cover art
    if track["track_covers"]:
        with requests.get(track["track_covers"][0], stream=True) as request:
            if request:
                with open("cover.jpg", "wb") as file:
                    file.write(request.content)

                md["disposition:v"] = "attached_pic"
                md["id3v2_version"] = 3

                inputs.append(ffmpeg.input("cover.jpg"))

    p = ffmpeg.output(*inputs, "mu.mp3", acodec="copy", **md).overwrite_output()
    # print(*ffmpeg.get_args(p))

    print(f"{desc}: merging...          ", end="\r")
    p.run(quiet=True)

    util.delete_file(final_name)
    os.rename("mu.mp3", final_name)
    util.delete_file("mu.ts")
    util.delete_file("cover.jpg")

    size = util.sizeof_fmt(os.path.getsize(final_name))
    log.success("%s (%s)" % (desc, size))


if __name__ == "__main__":

    def rqst_id(uid):
        uid = util.str_toplus(uid)

        check_group = rqst_method("groups.getById", {"group_ids": uid})
        check_user = rqst_method("users.get", {"user_ids": uid})

        if check_user:
            i = util.str_toplus(check_user[0]["id"])
            n = f"{check_user[0]['first_name']} {check_user[0]['last_name']}"
        elif check_group:
            i = util.str_tominus(check_group[0]["id"])
            n = check_group[0]["name"]
        else:
            return None

        return {"id": i, "name": n}

    def rqst_album(album):
        if "access_hash" not in album:
            album["access_hash"] = ""

        if "title" not in album:
            log.info("album w/o title, trying to guess...")
            try:
                for al in vk_audio.get_albums_iter(owner_id=album["owner_id"]):
                    if int(al["id"]) == int(album["id"]) and "title" in al:
                        log.info("found: %s" % al["title"])
                        album["title"] = al["title"]

                if "title" not in album:
                    raise Exception
            except:
                log.warning("failed ToT")
                album["title"] = ""

        path = "%s - (%s)" % (util.str_cut(album["title"], 200), album["id"])
        path = util.esc(path, 0)
        os.makedirs(path, exist_ok=True)
        os.chdir(path)

        try:
            for track in vk_audio.get_iter(
                album["owner_id"], album["id"], album["access_hash"]
            ):
                rqst_multiple(track)
        except AccessDenied:
            log.error(f"no access | {path}")

        os.chdir("..")

    log.remove(0)
    log.add(
        sys.stderr,
        backtrace=True,
        diagnose=True,
        format="<level>[{time:HH:mm:ss}]</level> {message}",
        colorize=True,
        level=5,
    )

    if not util.check_ffmpeg():
        log.error("ffmpeg not found")
        sys.exit()

    # parse args
    parser = optparse.OptionParser()
    parser.add_option(
        "-l", "--login", dest="login_info", default="", help="Login info (login:pass)"
    )
    parser.add_option(
        "-t",
        "--threads",
        dest="m3u8_threads",
        type=int,
        default="3",
        help="m3u8 threads",
    )
    parser.add_option(
        "-m", "--music", dest="music", action="store_true", help="dump music"
    )
    parser.add_option(
        "-a", "--album", dest="album", action="store_true", help="dump albums/playlists"
    )
    parser.add_option(
        "-e",
        "--exists",
        dest="skip_existing",
        action="store_true",
        default=False,
        help="Skip existing files",
    )
    parser.add_option(
        "-r",
        "--range",
        dest="range",
        default="",
        help="range to dump music (1,2,4,10-12)",
    )
    parser.add_option("-q", "--query", dest="query", default="", help="query to search")
    parser.add_option(
        "-c", "--count", dest="count", default=20, help="items count for query"
    )
    options, arguments = parser.parse_args()

    m3u8_threads = options.m3u8_threads
    skip_existing = options.skip_existing

    if options.range:
        spl = util.expand_ranges(options.range).split(",")
        ranges = [int(x.strip("'")) for x in spl]

    if ":" not in options.login_info:
        options.login_info = f"{input('Login: ')}:{input('Pass: ')}"

    lp = options.login_info.split(":")
    vk_session = VkApi(lp[0], lp[1], app_id=2685278)

    try:
        vk_session.auth()
        vk_audio = audio.VkAudio(vk_session)
    except AuthError as e:
        log.error("autechre error: %s" % str(e))
        sys.exit(1)

    if options.query:
        r = ""
        tracks = []
        all_tracks = ["no"]  # 1

        for i, track in enumerate(
            vk_audio.search_iter(options.query, offset=10), start=1
        ):
            print(f"   {i}\t| {track['artist']} - {track['title']}")
            tracks.append(track)

            if len(tracks) < int(options.count):
                continue

            all_tracks += tracks
            tracks = []
            r = input("choose range (1,3,5-7) to dump, 0 to continue: ")

            if r != "0":
                break

        spl = util.expand_ranges(r).split(",")
        rng = [int(x.strip("'")) for x in spl]

        if not rng:
            sys.exit()

        path = util.esc(options.query)
        os.makedirs(path, exist_ok=True)
        os.chdir(path)

        for i, track in enumerate(all_tracks, start=0):
            if track == "no" or i not in rng:
                continue
            print(track)
            rqst_multiple(track)

        os.chdir("..")

        sys.exit()

    if not arguments:
        me = rqst_method("users.get")[0]["id"]
        arguments.append(str(me))

    for i, arg in enumerate(arguments, start=1):
        for p in ["https://", "vk.com/", "music/"]:
            arg = arg.removeprefix(p)

        if arg.startswith("playlist/"):
            arg = arg.removeprefix("playlist/")

            al = {}
            try:
                al["owner_id"], al["id"], al["access_hash"] = arg.split("_")
            except:
                al["owner_id"], al["id"] = arg.split("_")

            rqst_album(al)
            print("")
            continue

        if arg[:+5] in ["audio", "[[aud"]:
            for p in ["[[", "audios", "audio"]:
                arg = arg.removeprefix(p)
            arg = arg.removesuffix("]]")

            track = vk_audio.get_audio_by_id(arg.split("_"))
            rqst_multiple(track)

            continue

        target = rqst_id(arg)
        if not target:
            log.error("%s invalid." % arg)
            continue

        log.info(f"{i} / {len(arguments)} | {target['name']}")

        path = "%s (%s)" % (target["name"], target["id"])
        path = util.escut(path)

        os.makedirs(path, exist_ok=True)
        os.chdir(path)

        if not options.album and not options.music:
            log.warning("no '-m' or '-a' option, dumping all")
            options.album = options.music = True

        if options.album:
            log.info("looking for albums...")
            albums_list = vk_audio.get_albums(owner_id=target["id"])

            for i, album in enumerate(albums_list, start=1):
                if ranges and i not in ranges:
                    if i > max(ranges):
                        break
                    continue

                log.info(f"{i} / {len(albums_list)} | {album['title']}")
                rqst_album(album)
                print("")

        if options.music and not (options.album and ranges):
            log.info("downloading tracks...")

            for i, track in enumerate(
                vk_audio.get_iter(owner_id=target["id"]), start=1
            ):
                if ranges and i not in ranges:
                    if i > max(ranges):
                        break
                    continue

                rqst_multiple(track)

        os.chdir("..")
