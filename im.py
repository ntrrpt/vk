#!/usr/bin/env python3
from datetime import datetime, timedelta
import sys
import json
import time
import random
import os
import io
import re
import pathlib
import shutil
import requests
import argparse

from blank import mainfile, def_blank, fwd_blank, jnd_blank
import mu
import util

import yt_dlp
from PIL import Image
from tabulate import tabulate
from loguru import logger as log
from vk_api import VkApi, audio
from vk_api.exceptions import AuthError, Captcha

prev_id = prev_date = offset_count = items_done = 0
vk_cookies = "# Netscape HTTP Cookie File\n"
progress_str = ""


def progress(string, force=False):
    if not force and args.verbose:
        log.info(string)
        return

    print(" " * os.get_terminal_size().columns, end="\r")
    print(string, end="\r")


def rqst_file(url, path):
    if not url:
        return

    # TODO: bytes mismatch detection
    if os.path.exists(path) and not args.rewrite:
        return

    block_size = 1024
    max_tries = 5
    dw_total = 0

    while max_tries:
        try:
            with requests.get(url, stream=True, timeout=10) as request:
                if not request:
                    log.error(f"({request.status_code}) {path}")
                    return

                cl = int(request.headers.get("Content-Length", "0")) or 10000
                dw_len = util.float_fmt(cl / 1048576, 2)

                progress(f"{progress_str} | {dw_len}MB {path}")

                now = time.time()
                with open(path, "wb", buffering=block_size) as file:
                    for chunk in request.iter_content(chunk_size=block_size):
                        file.write(chunk)
                        dw_total += len(chunk)

                        if time.time() - now > 2:
                            now = time.time()
                            dw_now = util.float_fmt(dw_total / 1048576, 2)
                            m = f"{progress_str} | {dw_now}MB / {dw_len}MB {path}"
                            progress(m, True)
            return
        except:
            log.warning(f"{progress_str} | retry {path}")
            max_tries -= 1

    log.error(f"{progress_str} | timeout {path}")


def str_esc(string, url_parse=False):
    url_regex = r"[-a-zA-Zа-яА-Я0-9@:%_\+.~#?&//=]{2,256}\.[a-zA-Zа-яА-Я0-9]{2,4}\b(\/[-a-zA-Zа-яА-Я0-9@:%_\+.~#?&//=]*)?"
    html_escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
        ">": "&gt;",
        "<": "&lt;",
        "\n": "<br/>\n" if url_parse else "\n",
    }

    string = "".join(html_escape_table.get(c, c) for c in string)

    if not url_parse:
        return string

    replaced = []
    link_matches = re.finditer(url_regex, string)  # , re.MULTILINE)
    for match in link_matches:
        mg = match.group()
        if mg not in replaced and mg.startswith(("http", "vk.com")):
            replaced.append(mg)
            string = string.replace(
                mg, f'<a href="{mg}" title="{mg}">{util.str_cut(mg, 50)}</a>'
            )

    return string


def rqst_thumb(path, th_w, th_h):
    try:
        img = Image.open(path).convert("RGB")
    except:
        log.error("corrupted image %s" % path)
        return {"path": "broken", "height": 100, "width": 100}

    src_w, src_h = img.size
    if src_w > th_w or src_h > th_h:
        path = "photos/thumbnails/th_" + os.path.basename(path)
        img.thumbnail((th_w, th_h))
        src_w, src_h = img.size
        img.save(path)
    else:
        path = "photos/" + os.path.basename(path)

    return {"path": path, "height": src_h, "width": src_w}


def rqst_photo(input):
    photo = {"url": "null", "height": 100, "width": 100}
    current = 0
    for size in input["sizes"]:
        if size["type"] == "w":
            photo = size
            break
        elif size["type"] == "s" and current < 1:
            current = 1
            photo = size
        elif size["type"] == "m" and current < 2:
            current = 2
            photo = size
        elif size["type"] == "x" and current < 3:
            current = 3
            photo = size
        elif size["type"] == "y" and current < 4:
            current = 4
            photo = size
        elif size["type"] == "z" and current < 5:
            current = 5
            photo = size

    return {"url": photo["url"], "height": photo["height"], "width": photo["width"]}


def rqst_user(user_id, save=True):
    for i in range(len(users)):
        if users[i]["id"] == user_id:
            return users[i]

    if user_id > 0:
        r = rqst_method("users.get", {"user_ids": user_id, "fields": "photo_200"})[0]
        user = {
            "id": user_id,
            "photo": r["photo_200"],
            "name": r["first_name"] + " " + r["last_name"],
        }
    else:
        r = rqst_method(
            "groups.getById",
            {"group_id": util.str_toplus(user_id), "fields": "photo_200"},
        )[0]
        user = {"id": user_id, "photo": r["photo_200"], "name": r["name"]}

    if save:
        rqst_file(user["photo"], "userpics/id%s.jpg" % user_id)
        users[len(users)] = user

    return user


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


def rqst_message_service(input):
    goto_link = '<a href="#go_to_message%d" onclick="return GoToMessage(%d)" title="%s" style="color: #70777b">%s</a>'
    url_link = '<a href="%s" style="color: #70777b">%s</a>'

    from_id = rqst_user(input["from_id"])
    from_prefix = "https://vk.com/" + ("id" if from_id["id"] > 0 else "club")

    message = ""
    TYPE = input["action"]["type"]

    match TYPE:
        case "chat_create":
            message = (
                url_link
                % (from_prefix + util.str_toplus(from_id["id"]), from_id["name"])
                + f" создал беседу «{input['action']['text']}»"
            )

        case "chat_title_update":
            message = (
                url_link
                % (from_prefix + util.str_toplus(from_id["id"]), from_id["name"])
                + f" изменил название беседы на «{input['action']['text']}»"
            )

        case "chat_invite_user_by_link":
            message = (
                url_link % (from_prefix + str(from_id["id"]), from_id["name"])
                + " присоединился к беседе по ссылке"
            )

        case "chat_photo_update":
            rqst_file(
                rqst_photo(input["attachments"][0]["photo"])["url"],
                f"userpics/up{input['conversation_message_id']}.jpg",
            )

            message = (
                f"{url_link % (from_prefix + util.str_toplus(from_id['id']), from_id['name'])} обновил фотографию беседы\n"
                f'<div class="userpic_wrap">'
                f'    <a class="userpic_link" href="userpics/up{input["conversation_message_id"]}.jpg">\n'
                f'        <img class="userpic" src="userpics/up{input["conversation_message_id"]}.jpg" style="width: 60px; height: 60px">'
                f"    </a>"
                f"</div>\n"
            )

        case "chat_photo_remove":
            message = f"{url_link % (from_prefix + util.str_toplus(from_id['id']), from_id['name'])} удалил фотографию беседы\n"

        case "chat_pin_message" | "chat_unpin_message":
            prefix = " закрепил " if TYPE == "chat_pin_message" else " открепил "
            member_id = rqst_user(input["action"]["member_id"])
            message = (
                url_link % (from_prefix + str(member_id["id"]), member_id["name"])
                + prefix
            )

            if "message" in input["action"]:
                message += "сообщение: " + goto_link % (
                    input["action"]["conversation_message_id"],
                    input["action"]["conversation_message_id"],
                    input["action"]["message"],
                    f"«{input['action']['message']}»",
                )
            else:
                message += goto_link % (
                    input["action"]["conversation_message_id"],
                    input["action"]["conversation_message_id"],
                    "",
                    "сообщение",
                )

        case "chat_invite_user" | "chat_kick_user":
            us_prefix = (
                "https://vk.com/id" if input["from_id"] > 0 else "https://vk.com/club"
            )
            us_postfix = (
                "https://vk.com/id"
                if input["action"]["member_id"] > 0
                else "https://vk.com/club"
            )

            if TYPE == "chat_invite_user":
                self_prefix = " вернулся в беседу"
                other_prefix = " пригласил "
            else:
                self_prefix = " вышел из беседы"
                other_prefix = " исключил "

            if input["from_id"] == input["action"]["member_id"]:
                message = (
                    url_link
                    % (us_prefix + util.str_toplus(from_id["id"]), from_id["name"])
                    + self_prefix
                )
            else:
                passive = rqst_user(input["action"]["member_id"])
                message = (
                    url_link
                    % (us_prefix + util.str_toplus(from_id["id"]), from_id["name"])
                    + other_prefix
                    + url_link
                    % (us_postfix + util.str_toplus(passive["id"]), passive["name"])
                )

        case _:
            log.error(f"missing_service: {input}")

    return f'\n<div class="message service" id="message{input["id"]}"><div class="body details">\n    {message}</div>\n</div>\n'


def rqst_attachments(input):
    sw_joined = False
    pre_attachments = post_attachments = ""

    data_blank = (
        "%s\n"
        '   <div class="fill pull_left"></div>\n'
        '   <div class="body">\n'
        '       <div class="title bold">%s</div>\n'
        '       <div class="status details">%s</div>\n'
        "   </div>"
        "</a>\n"
    )

    human_date = datetime.fromtimestamp(input["date"]).strftime("%y-%m-%d_%H-%M-%S")

    if "geo" in input:
        sw_joined = True
        html_details = "%s %s" % (
            input["geo"]["coordinates"]["latitude"],
            input["geo"]["coordinates"]["longitude"],
        )

        if "place" in input["geo"]:
            html_details = "%s (%s)" % (input["geo"]["place"]["title"], html_details)

        pre_attachments = '<div class="media_wrap clearfix">\n%s</div>\n' % (
            data_blank
            % (
                '<a class="media clearfix pull_left block_link media_location">',
                "Местоположение",
                html_details,
            )
        )

    for i in range(len(input["attachments"])):
        a = input["attachments"][i]
        TYPE = a["type"]

        data_fragment = "missing_attachment = %s" % a
        json_fragment = ""
        if not args.nojson:
            json_fragment = f'title="{str_esc(json.dumps(a, indent=10, ensure_ascii=False, sort_keys=True))}"'

        match TYPE:
            case "video":
                # TODO: need 'remixnsid' cookie for private videos
                v_id = "%s_%s" % (a["video"]["owner_id"], a["video"]["id"])
                link = "https://vk.com/video" + v_id
                href = f"videos/{util.escut(a['video']['title'])} ({v_id}).mp4"

                try:
                    if args.novideo:
                        raise StopIteration

                    if os.path.exists(href):
                        if not args.rewrite:
                            raise StopIteration
                        util.delete(href)

                    opts = {
                        "quiet": not args.verbose,
                        "verbose": False,
                        "outtmpl": href,
                        "format": "best",
                        "extractor_retries": 2,
                        "fragment_retries": 2,
                        "socket_timeout": 20,
                        "retries": 2,
                        "cookiefile": io.StringIO(vk_cookies),
                    }

                    # byedpi
                    # opts['proxy']: "socks5://localhost:1080"

                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([link])

                    if args.verbose:
                        log.trace(f"{progress_str} | {href}")

                except StopIteration:
                    pass

                except:
                    if args.verbose:
                        log.warning(f"{progress_str} | {href}")
                    href = link

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_video" {json_fragment} href="{href}">',
                    f"{a['video']['title']}",
                    f"{timedelta(seconds=int(a['video']['duration']))} | {a['video']['owner_id']}_{a['video']['id']}",
                )

            case "audio":
                artist = util.str_cut(a["audio"]["artist"], 100, "")
                title = util.str_cut(a["audio"]["title"], 100, "")
                audio_name = "%s - %s" % (artist, title)
                audio_name = "%s (%s_%s)" % (
                    audio_name,
                    a["audio"]["owner_id"],
                    a["audio"]["id"],
                )
                audio_name = util.escut(audio_name)

                try:
                    href = f"music/{audio_name}.mp3"
                    if args.nomusic:
                        raise Exception()

                    if os.path.exists(href):
                        if not args.rewrite:
                            raise StopIteration
                        util.delete(href)

                    audio = vk_audio.get_audio_by_id(
                        a["audio"]["owner_id"], a["audio"]["id"]
                    )
                    mu.rqst_multiple(audio, href)

                except StopIteration:
                    if args.verbose:
                        log.info(f"{progress_str} | {href}")
                    pass
                except:
                    href = f"https://m.vk.com/audio{a['audio']['owner_id']}_{a['audio']['id']}"

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_audio_file" {json_fragment} href="{href}">',
                    audio_name,
                    f"{timedelta(seconds=int(a['audio']['duration']))} | {a['audio']['owner_id']}_{a['audio']['id']} ",
                )

            case "wall":
                href = f"https://vk.com/wall{a['wall']['to_id']}_{a['wall']['id']}"
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{href}">',
                    "Запись",
                    href,
                )

            case "poll":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="https://vk.com/poll{a["poll"]["owner_id"]}_{a["poll"]["id"]}">',
                    "Опрос",
                    f"id{a['poll']['question']}",
                )

            case "gift":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{a["gift"]["thumb_256"]}">',
                    "Подарок",
                    f"id{a['gift']['id']}",
                )

            case "link":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{a["link"]["url"]}">',
                    a["link"]["title"],
                    a["link"]["caption"] if "caption" in a["link"] else "",
                )

            case "market":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_invoice" {json_fragment} href="https://vk.com/market{a["market"]["owner_id"]}_{a["market"]["id"]}">',
                    a["market"]["title"],
                    a["market"]["price"]["text"],
                )

            case "wall_reply":
                if "deleted" in a["wall_reply"]:
                    html_title = "Комментарий к записи (удалён)"
                    href = ""
                else:
                    html_title = "Комментарий к записи"
                    href = f"https://vk.com/wall{a['wall_reply']['owner_id']}_{a['wall_reply']['post_id']}?reply={a['wall_reply']['id']}"

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{href}">',
                    html_title,
                    href,
                )

            case "doc":
                # what
                namefile = util.escut(a["doc"]["title"], 80)
                if namefile[-len(a["doc"]["ext"]) :] == a["doc"]["ext"]:
                    namefile = namefile[: -len(a["doc"]["ext"]) - 1]

                if args.nodoc:
                    href = a["doc"]["url"]
                else:
                    href = f"docs/{namefile}-{i}-{input['conversation_message_id']}_{human_date}.{a['doc']['ext']}"
                    rqst_file(a["doc"]["url"], href)

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_file" {json_fragment} href="{href}">',
                    namefile + "." + a["doc"]["ext"],
                    f"{util.sizeof_fmt(a['doc']['size'])} ({a['doc']['owner_id']}_{a['doc']['id']})",
                )

            case "call":
                html_title = (
                    "Исходящий "
                    if input["from_id"] == a["call"]["initiator_id"]
                    else "Входящий "
                )
                html_title += "видеозвонок" if a["call"]["video"] else "звонок"

                match a["call"]["state"]:
                    case "canceled_by_initiator":
                        html_details = "Отменён"
                    case "canceled_by_receiver":
                        html_details = "Отклонён"
                    case "reached":
                        html_details = f"Завершен ({timedelta(seconds=int(a['call']['duration']))})"

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_call" {json_fragment}>',
                    html_title,
                    html_details,
                )

            case "graffiti":
                if args.nograffiti:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{a["graffiti"]["url"]}">',
                        "Граффити",
                        f"{a['graffiti']['height']}x{a['graffiti']['width']}",
                    )
                else:
                    namefile = f"graffiti-{input['conversation_message_id']}-{i}_{human_date}.jpg"
                    rqst_file(a["graffiti"]["url"], "photos/" + namefile)
                    thumb = rqst_thumb("photos/" + namefile, 350, 300)

                    data_fragment = (
                        f'<a class="photo_wrap clearfix pull_left" href="photos/{namefile}">\n'
                        f'<img class="photo" src="{thumb["path"]}" style="width: {thumb["width"]}px; height: {thumb["height"]}px"/></a>'
                    )

            case "audio_message":
                if args.novoice:
                    href = a["audio_message"]["link_ogg"]
                else:
                    href = f"voice_messages/audio-{i}-{input['conversation_message_id']}_{human_date}.ogg"
                    rqst_file(a["audio_message"]["link_ogg"], href)

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_voice_message" {json_fragment} href="{href}">',
                    "Голосовое сообщение",
                    timedelta(seconds=int(a["audio_message"]["duration"])),
                )

            case "sticker":
                if args.nosticker:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{a["sticker"]["images"][1]["url"]}">',
                        "Стикер",
                        f"id{a['sticker']['sticker_id']}",
                    )
                else:
                    rqst_file(
                        a["sticker"]["images"][1]["url"],
                        f"userpics/st{a['sticker']['sticker_id']}.jpg",
                    )

                    data_fragment = (
                        f'<a class="sticker_wrap clearfix pull_left" href="userpics/st{a["sticker"]["sticker_id"]}.jpg">\n'
                        f'<img class="sticker" src="userpics/st{a["sticker"]["sticker_id"]}.jpg" style="width: 128px; height: 128px"/></a>'
                    )

            case "photo":
                p = rqst_photo(a["photo"])

                if args.nophoto:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{p["url"]}">',
                        "Фото",
                        f"{p['height']}x{p['width']}",
                    )
                else:
                    photo_date = datetime.fromtimestamp(a["photo"]["date"]).strftime(
                        "%y-%m-%d_%H-%M-%S"
                    )
                    namefile = (
                        f"ph-{input['conversation_message_id']}-{i}_{photo_date}.jpg"
                    )
                    rqst_file(p["url"], "photos/" + namefile)
                    thumb = rqst_thumb("photos/" + namefile, 350, 280)

                    data_fragment = (
                        f'<a class="photo_wrap clearfix pull_left" href="photos/{namefile}">\n'
                        f'<img class="photo" src="{thumb["path"]}" style="width: {thumb["width"]}px; height: {thumb["height"]}px"/></a>'
                    )

            case _:
                log.error(f"missing_attachment: {a}")

        if sw_joined:
            post_attachments += (
                f'<div class="message default clearfix joined">\n'
                f'    <div class="body">{data_fragment}\n'
                f"    </div>\n"
                f"</div>\n"
            )
        else:
            pre_attachments = (
                f'<div class="media_wrap clearfix">\n{data_fragment}</div>\n'
            )
            sw_joined = True

    return (pre_attachments, post_attachments)


def rqst_message(input, forwarded=False):
    global prev_id, prev_date
    fwd_messages = ""
    from_id = rqst_user(input["from_id"])

    # url selection
    if from_id["id"] > 0:
        sender = f'<a href="https://vk.com/id{from_id["id"]}">{from_id["name"]}</a>'
    else:
        sender = f'<a href="https://vk.com/club{util.str_toplus(from_id["id"])}">{from_id["name"]}</a>'

    # message sending/changing time
    date = datetime.fromtimestamp(input["date"]).strftime("%d/%m/%y %H:%M:%S")
    if "update_time" in input:
        date = f"({datetime.fromtimestamp(input['update_time']).strftime('%H:%M:%S')}) {date}"

    # missing id fix
    if "conversation_message_id" not in input:
        input["conversation_message_id"] = random.randint(-100, -1)

    # reply message
    if "reply_message" in input:
        if "conversation_message_id" in input["reply_message"]:
            fwd_messages += rqst_message(input["reply_message"], True)
        else:
            fwd_messages += f'<div title="{input["reply_message"]}" class="reply_to details">Нет id пересланного сообщения</div>\n'

    # forwarded messages
    if "fwd_messages" in input:
        for i in input["fwd_messages"]:
            fwd_messages += rqst_message(i, True)

    # requesting attachments
    pre_attachments, post_attachments = rqst_attachments(input)

    # blank selection
    if forwarded:
        blank = fwd_blank
    elif prev_id == from_id["id"] and input["date"] - prev_date < 120:
        blank = jnd_blank
    else:
        prev_date = input["date"]
        prev_id = from_id["id"]
        blank = def_blank

    return blank % (
        input["conversation_message_id"],
        from_id["id"],
        from_id["id"],
        sender if forwarded else date,
        date if forwarded else sender,
        fwd_messages,
        str_esc(input["text"], True),
        '<div class="message default"></div>\n'
        if input["text"] and forwarded and "fwd_messages" not in input
        else "" + pre_attachments,
        post_attachments,
    )


def makehtml(filename, page, count, target, chat, const_offset_count):
    global progress_str, items_done, offset_count
    for i in range(args.pagenum):
        # empty check
        while True:
            chunk = rqst_method(
                "messages.getHistory",
                {
                    "peer_id": target,
                    "count": 200,
                    "extended": 1,
                    "offset": offset_count * 200,
                },
            )
            if chunk["items"] or offset_count < 0:
                break

            offset_count -= 1

        for msg in reversed(chunk["items"]):
            items_done += 1

            # html msg
            util.append(
                filename,
                rqst_message_service(msg) if "action" in msg else rqst_message(msg),
            )

            # json msg
            s = ",%s"
            if not os.path.isfile("result.json"):
                util.append("result.json", "[")
                s = "%s"

            util.append("result.json", s % json.dumps(msg, ensure_ascii=False))

            # status stuff
            progress_str = f"[{util.escut(chat['title'], 20)}]"
            progress_str += f" {util.float_fmt((items_done) / count * 100, 1)}%"
            progress_str += f" {items_done}/{count}"
            progress_str += f" u{len(users)}"
            progress_str += f" pg{page + 1}/{count // (200 * args.pagenum) + 1}"
            progress_str += f" pgch{i + 1}/{args.pagenum}"
            progress_str += (
                f" allch{const_offset_count - offset_count}/{const_offset_count}"
            )

            progress(progress_str)

        offset_count -= 1


def makedump(target):
    global items_done, offset_count, progress_str

    start_time = time.time()
    me = rqst_method("users.get")[0]

    # html header generation
    if target > 2e9:
        r = rqst_method(
            "messages.getChat", {"chat_id": target - int(2e9), "fields": "photo_200"}
        )

        if r is None:
            log.error("no access to %s" % target)
            return

        chat = {
            "title": r["title"],
            "photo": r["photo_200"]
            if "photo_200" in r
            else "https://vk.com/images/deactivated_200.png",
        }

        admin = rqst_user(r["admin_id"], False)

        info = (
            f"Название: {chat['title']}\n"
            f"Сохранено в: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Сидящий: {me['first_name']} {me['last_name']} ({me['id']})\n"
            f"Админ: {admin['name']} ({admin['id']})\n"
            f"Юзеров: {r['members_count']}"
        )

    else:
        r = rqst_user(target, False)
        chat = {"title": r["name"], "photo": r["photo"]}

        if r is None:
            log.error("no access to %s" % target)
            return

        info = (
            f"Название: {chat['title']}\n"
            f"Сохранено в: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Сидящий: {me['first_name']} {me['last_name']} ({me['id']})"
        )

    # directory preparation
    d = util.escut(chat["title"], 40)
    work_dir = "%s (%s)" % (d, target)

    shutil.copytree("blank", work_dir, dirs_exist_ok=True)
    os.chdir(work_dir)

    for DIR in [
        "voice_messages",
        "music",
        "videos",
        "photos/thumbnails",
        "docs",
        "userpics",
    ]:
        os.makedirs(DIR, exist_ok=True)

    # chat pfp
    rqst_file(chat["photo"], "userpics/main.jpg")

    # html page creation
    count = rqst_method("messages.getHistory", {"peer_id": target, "count": 0})["count"]

    const_offset_count = offset_count = count // 200 + 1
    page_count = count // (200 * args.pagenum) + 1

    for page in range(page_count):
        filename = "messages%s.html" % (page + 1)
        pathlib.Path(filename).unlink(missing_ok=True)

        # html header
        util.append(
            filename, mainfile % (str_esc(chat["title"]), info, str_esc(chat["title"]))
        )

        # to the previous page
        if page:
            a = f'\n<a class="pagination block_link" href="messages{page}.html">Предыдущая страница ( {page} / {page_count} )</a>\n'
            util.append(filename, a)

        # writing messages
        makehtml(filename, page, count, target, chat, const_offset_count)

        # to the next page
        if page + 1 != page_count:
            a = f'\n<a class="pagination block_link" href="messages{page + 2}.html">Cледующая страница ( {page + 2} / {page_count} )</a>\n'
            util.append(filename, a)

        # html eof
        util.append(filename, "</div></div></div></body></html>")

        # prettify
        util.html_fmt(filename)

    # json eof
    util.append("result.json", "]")

    # beatify json + irc.txt generation
    with open("result.json", "r", encoding="utf-8") as f:
        d = json.load(f)

    table = []

    for msg in d:
        if any(("text" not in msg, not msg["text"])):
            continue

        u = rqst_user(msg["from_id"])
        table.append([u["name"], msg["text"]])

    util.append("irc.txt", tabulate(table, tablefmt="plain"))

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4, ensure_ascii=False)

    end_time = util.float_fmt(time.time() - start_time, 0)
    end_time = timedelta(seconds=int(end_time))

    log.success(f"{chat['title']} finished in {end_time} ")
    os.chdir("..")


if __name__ == "__main__":
    # fmt: off
    ap = argparse.ArgumentParser()

    g = ap.add_argument_group('main options')
    add = g.add_argument

    add("-a", "--auth",    default="",             help="login info (token or login:pass)")
    add("-n", "--pagenum", type=int, default=1000, help="number of messages in one html file")
    add("-r", "--rewrite", action="store_true",    help="force rewriting files")
    add("-t", "--threads", type=int, default=5,    help="number of threads for m3u8 downloading")
    add("-v", "--verbose", action="store_true",    help="verbose logging to file")

    g = ap.add_argument_group('filter options')
    add = g.add_argument

    add("--novoice",    action="store_true", help="don't save voice messages")
    add("--nomusic",    action="store_true", help="don't save music files")
    add("--novideo",    action="store_true", help="don't save video files")
    add("--nophoto",    action="store_true", help="don't save pictures")
    add("--nograffiti", action="store_true", help="don't save graffiti")
    add("--nosticker",  action="store_true", help="don't save stickers")
    add("--nodoc",      action="store_true", help="don't save documents")
    add("--nojson",     action="store_true", help="don't save json applications")
    add("--noall",      action="store_true", help="don't save anything (except json)")

    ap.add_argument("targets", nargs="*", help="dialogs to dump")

    args = ap.parse_args()
    # fmt: on

    if args.noall:
        args.nomusic = True
        args.novideo = True
        args.novoice = True
        args.nophoto = True
        args.nograffiti = True
        args.nosticker = True
        args.nodoc = True

    args.pagenum = args.pagenum // 200 + 1

    log.remove(0)
    log.add(
        sys.stderr,
        backtrace=True,
        diagnose=True,
        format="<level>[{time:HH:mm:ss}]</level> {message}",
        colorize=True,
        level=5,
    )

    # not very helpful tbh
    def rqst_cookies(login):
        ret = "# Netscape HTTP Cookie File\n"
        try:
            with open("vk_config.v2.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            return ret

        if login in data:
            for cookie in data[login]["cookies"]:
                ret += "%s\tTRUE\t/\tTRUE\t0\t%s\t%s\n" % (
                    cookie["domain"],
                    cookie["name"],
                    cookie["value"],
                )

        return ret

    def rqst_dialogs():
        conversations = []
        count = rqst_method("messages.getConversations", {"count": 0})["count"]
        range_count = count // 200 + 1

        for offset in range(range_count):
            if range_count > 1:
                progress("loading dialogs %s/%s" % (offset, range_count))

            chunk = rqst_method(
                "messages.getConversations",
                {"count": 200, "extended": 1, "offset": offset * 200},
            )

            for item in chunk["items"]:
                conv_id = item["conversation"]["peer"]["id"]

                if conv_id not in conversations:
                    conversations.append(conv_id)

        log.info("loaded %s dialogs!" % len(conversations))
        return conversations

    if not args.auth:
        args.auth = f"{input('Login: ')}:{input('Pass: ')}"

    if ":" in args.auth:
        lp = args.auth.split(":")
        vk_session = VkApi(lp[0], lp[1], app_id=6287487)

        try:
            vk_session.auth()
            vk_audio = audio.VkAudio(vk_session)

            try:
                with open("cookies.txt") as f:
                    vk_cookies = f.read()
            except:
                vk_cookies = rqst_cookies(lp[0])

        except AuthError as ex:
            log.error("autechre error: %s" % str(ex))
            sys.exit(1)

        except Captcha as ex:
            log.warning("captcha url: %s" % ex.get_url())
            sys.exit(1)

    elif len(args.auth) >= 85:
        vk_session = VkApi(token=args.auth)
        log.warning("token used, music will not dumped")
        args.skip_music = True

    else:
        log.error("login info is invalid!")
        sys.exit(1)

    me = rqst_method("users.get")[0]
    me_fl = util.esc(me["first_name"] + " " + me["last_name"])
    m = "%s (%s)" % (me_fl, me["id"])

    if args.verbose:
        log.add(
            "%s.txt" % m,
            backtrace=True,
            diagnose=True,
            colorize=False,
            level=5,
        )
    log.info(m)

    conversations = rqst_dialogs()

    if not args.targets:
        # no args = dump all
        start_time = time.time()

        me_dir = f"Диалоги {util.escut(me['first_name'] + ' ' + me['last_name'])} ({me['id']})"
        os.makedirs(me_dir, exist_ok=True)
        if not os.path.exists(f"{me_dir}/blank"):
            shutil.copytree("blank", f"{me_dir}/blank")
        os.chdir(me_dir)

        for i in range(len(conversations)):
            users = {}
            prev_id = items_done = prev_date = 0
            progress_str = ""
            makedump(conversations[i])

        # FIXME: stopwatch
        end_time = util.float_fmt(time.time() - start_time, 0)
        end_time = timedelta(seconds=int(end_time))

        log.info("all saved in: %s" % end_time)

        shutil.rmtree("blank")
        sys.exit()

    for t in args.targets:
        users = {}
        prev_id = items_done = prev_date = 0
        progress_str = ""

        if t == "me":
            makedump(rqst_method("users.get")[0]["id"])

        elif t.startswith("@"):
            makedump(2000000000 + int(t[1:]))

        else:
            work = None

            if isinstance(work, int):
                work = abs(work)

            check_group = rqst_method("groups.getById", {"group_ids": t})
            check_user = rqst_method("users.get", {"user_ids": t})

            # сhecking for id in dialogs (can be disabled)
            if check_group is not None and -check_group[0]["id"] in conversations:
                work = util.str_tominus(check_group[0]["id"])
            if check_user is not None and check_user[0]["id"] in conversations:
                work = util.str_toplus(check_user[0]["id"])

            if work is None:
                log.error(f"{t} is invalid")
            else:
                makedump(int(work))
