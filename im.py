#!/usr/bin/env python3
import sys
import json
import time
import random
import optparse
import threading
import math
import os
import re
import datetime, pathlib
import shutil, contextlib
import requests
import ffmpeg, multiprocessing
from loguru import logger

from vk_api import VkApi
from vk_api import audio
from vk_api.exceptions import AuthError, VkApiError

from PIL import Image

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

import mus

prev_id = prev_date = offset_count = items_done = 0
progress_str = ''

parser = optparse.OptionParser()
parser.add_option('--novoice',      dest='skip_voices',     action='store_true', help='Don\'t save voice messages')
parser.add_option('--nomusic',      dest='skip_music',      action='store_true', help='Don\'t save music files')
parser.add_option('--nophoto',      dest='skip_photos',     action='store_true', help='Don\'t save pictures')
parser.add_option('--nograffiti',   dest='skip_graffiti',   action='store_true', help='Don\'t save graffiti')
parser.add_option('--nostickers',   dest='skip_stickers',   action='store_true', help='Don\'t save stickers')
parser.add_option('--nodoc',        dest='skip_docs',       action='store_true', help='Don\'t save documents')
parser.add_option('--nojson',       dest='skip_json',       action='store_true', help='Don\'t save json applications')
parser.add_option('-a', '--noall',  dest='skip_all',        action='store_true', help='Don\'t save anything (except json)')
parser.add_option('-l', '--login',   dest='login_info', default='', help='Login info (token or login:pass)')
parser.add_option('-n', '--pagenum', dest='page_number', type=int, default='1000', help='Number of messages in one html file')
parser.add_option('-r', '--rewrite', dest='rewrite_files', action='store_true', help='Force rewriting files')
parser.add_option('-t', '--threads', dest='threads_count', type=int, default='5', help='Number of threads for m3u8 downloading')
parser.add_option('-v', '--verbse', dest='verbose', action='store_true', help='Verbose logging')
options, arguments = parser.parse_args()

if options.skip_all:
    options.skip_music = True
    options.skip_voices = True
    options.skip_photos = True
    options.skip_graffiti = True
    options.skip_stickers = True
    options.skip_docs = True

options.page_number = int(options.page_number) // 200 + 1

def text_append(dir, bin):
    with open(dir, 'a') as file:
        file.write(bin + '\n')

def progress(str):
    if options.verbose:
        logger.info(str)
    else:
        print(" " * os.get_terminal_size().columns, end = '\r')
        print(str , end = '\r')

def rqst_file(url, dir):
    block_size = 1024

    if not url or (os.path.exists(dir) and not options.rewrite_files):
        return

    with requests.get(url, stream=True, timeout=10) as request:
        if not request:
            logger.error(f'({request.status_code}) {dir}')
        else:
            dw_len = int(request.headers.get('Content-Length', '0')) or 10000
            progress(f'{progress_str} | {fix_val(dw_len / 1048576, 2)}MB {dir} ')
            with open(dir, 'wb', buffering = block_size) as file:
                for data in request.iter_content(chunk_size = block_size):
                    file.write(data)

def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0
    return "%3.1f %s" % (num, 'TB')

def fix_val(number, digits):
    return f'{number:.{digits}f}'

def str_toplus(string):
    string = str(string)
    return string[1:] if string[0] == '-' else string

def str_tominus(string):
    string = str(string)
    return '-' + string if string[0] != '-' else string

def str_fix(string, letters = 100):
    return str_cut(re.sub(r'[/\\?%*\-\[\]{}:|"<>]', '', string), letters)

def str_cut(string, letters, postfix='...'):
    return string[:letters] + (string[letters:] and postfix)

def str_esc(string, url_parse=False):
    url_regex = r"[-a-zA-Zа-яА-Я0-9@:%_\+.~#?&//=]{2,256}\.[a-zA-Zа-яА-Я0-9]{2,4}\b(\/[-a-zA-Zа-яА-Я0-9@:%_\+.~#?&//=]*)?"
    html_escape_table = {"&": "&amp;", '"': "&quot;", "'": "&apos;", ">": "&gt;", "<": "&lt;", "\n": "<br/>\n" if url_parse else "\n"}

    string = "".join(html_escape_table.get(c, c) for c in string)
    link_matches = re.finditer(url_regex, string)#, re.MULTILINE)

    if url_parse:
        replaced = []
        for match in link_matches:
            if match.group() not in replaced and match.group()[:+4] in ['http', 'vk.co']:
                replaced.append(match.group())
                string = string.replace(
                    match.group(),
                    f'<a href="{match.group()}" title="{match.group()}">{str_cut(match.group(), 50)}</a>'
                )

    return string

def rqst_thumb(input, th_w, th_h):
    try:
        image = Image.open(input).convert('RGB')
    except Exception:
        logger.error(f'corrupted image {input}  ')
        return {'path': 'broken', 'height': 100, 'width': 100}

    src_w, src_h = image.size
    if src_w > th_w or src_h > th_h:
        path = 'photos/thumbnails/th_' + os.path.basename(input)
        image.thumbnail((th_w, th_h))
        src_w, src_h = image.size
        image.save(path)
    else:
        path = 'photos/' + os.path.basename(input)

    return {'path': path, 'height': src_h, 'width': src_w}

def rqst_photo(input):
    photo = {'url': 'null', 'height': 100, 'width': 100}
    current = 0
    for size in input['sizes']:
        if size['type'] == 'w':
            photo = size
            break
        elif size['type'] == 's' and current < 1:
            current = 1
            photo = size
        elif size['type'] == 'm' and current < 2:
            current = 2
            photo = size
        elif size['type'] == 'x' and current < 3:
            current = 3
            photo = size
        elif size['type'] == 'y' and current < 4:
            current = 4
            photo = size
        elif size['type'] == 'z' and current < 5:
            current = 5
            photo = size
    return {'url': photo['url'], 'height': photo['height'], 'width': photo['width']}

def rqst_user(user_id, save=True):
    for i in range(len(users)):
        if users[i]['id'] == user_id:
            return users[i]

    if user_id > 0:
        r = rqst_method('users.get', {'user_ids': user_id, 'fields': 'photo_200'})[0]
        user = {
            'id': user_id,
            'photo': r['photo_200'], 
            'name': r['first_name'] + ' ' + r['last_name']
        }
    else:
        r = rqst_method('groups.getById', {'group_id': str_toplus(user_id), 'fields': 'photo_200'})[0]
        user = {
            'id': user_id, 
            'photo': r['photo_200'],
            'name': r['name']
        }

    if save:
        rqst_file(user['photo'], f'userpics/id{user_id}.jpg')
        users[len(users)] = user

    return user

def rqst_method(method, values={}):
    while True:
        try:
            r = vk_session.method(method, values)
            return r
        except Exception as ex:
            ex_str = str(ex)

            # invalid login/pass
            if '[5] User authorization failed:' in ex_str:
                logger.error('autechre error: ' + ex_str[31:])
                sys.exit()

            # invalid id
            if 'Invalid user id' in ex_str or 'group_ids is undefined' in ex_str:
                return None

            # idk
            if 'Internal server error' in ex_str:
                logger.warning(f'internal catched, waiting...   ')
                time.sleep(100)

            else:
                logger.error(f'execption in \'{method}\': {ex_str}   ')
                time.sleep(10)

def rqst_message_service(input):
    goto_link = '<a href="#go_to_message%d" onclick="return GoToMessage(%d)" title="%s" style="color: #70777b">%s</a>'
    url_link = '<a href="%s" style="color: #70777b">%s</a>'

    from_id = rqst_user(input['from_id'])
    from_prefix = 'https://vk.com/id' if from_id['id'] > 0 else 'https://vk.com/club'
    
    message = ''
    TYPE = input['action']['type']

    match TYPE:
        case "chat_create":
            message = url_link % (
                        from_prefix + str_toplus(from_id['id']),
                        from_id['name']
                    ) + f' создал беседу «{input["action"]["text"]}»'

        case "chat_title_update":
            message = url_link % (
                from_prefix + str_toplus(from_id['id']),
                from_id['name']
            ) + f' изменил название беседы на «{input["action"]["text"]}»'
        
        case "chat_invite_user_by_link":
            message = url_link % (
                from_prefix + str(from_id['id']),
                from_id['name']
            ) + ' присоединился к беседе по ссылке'
        
        case "chat_photo_update":
            rqst_file(rqst_photo(input['attachments'][0]['photo'])['url'], f'userpics/up{input["conversation_message_id"]}.jpg')

            message = (
                f'{url_link % (from_prefix + str_toplus(from_id["id"]), from_id["name"])} обновил фотографию беседы\n'
                f'<div class="userpic_wrap">'
                f'    <a class="userpic_link" href="userpics/up{input["conversation_message_id"]}.jpg">\n'
                f'        <img class="userpic" src="userpics/up{input["conversation_message_id"]}.jpg" style="width: 60px; height: 60px">'
                f'    </a>'
                f'</div>\n'
            )

        case "chat_photo_remove":
            message = (f'{url_link % (from_prefix + str_toplus(from_id["id"]), from_id["name"])} удалил фотографию беседы\n')

        case 'chat_pin_message' | 'chat_unpin_message':
            prefix = ' закрепил ' if TYPE == 'chat_pin_message' else ' открепил '
            member_id = rqst_user(input['action']['member_id'])
            message = url_link % (from_prefix + str(member_id['id']), member_id['name']) + prefix

            if 'message' in input['action']:
                message += 'сообщение: ' + goto_link % (
                    input['action']["conversation_message_id"],
                    input['action']["conversation_message_id"],
                    input['action']['message'],
                    f'«{input["action"]["message"]}»')
            else:
                message += goto_link % (
                    input['action']["conversation_message_id"],
                    input['action']["conversation_message_id"],
                    '',
                    'сообщение'
                )

        case 'chat_invite_user' | 'chat_kick_user':
            us_prefix = 'https://vk.com/id' if input['from_id'] > 0 else 'https://vk.com/club'
            us_postfix = 'https://vk.com/id' if input['action']['member_id'] > 0 else 'https://vk.com/club'

            if TYPE == 'chat_invite_user':
                self_prefix = ' вернулся в беседу'
                other_prefix = ' пригласил '
            else:
                self_prefix = ' вышел из беседы'
                other_prefix = ' исключил '

            if input['from_id'] == input['action']['member_id']:
                message = url_link % (us_prefix + str_toplus(from_id['id']), from_id['name']) + self_prefix
            else:
                passive = rqst_user(input['action']['member_id'])
                message = url_link % (
                    us_prefix + str_toplus(from_id['id']), 
                    from_id['name']
                ) + other_prefix + url_link % (
                    us_postfix + str_toplus(passive['id']), 
                    passive['name']
                )

        case _:
            logger.error(f'missing_service: {input}')

    return f'\n<div class="message service" id="message{input["id"]}"><div class="body details">\n    {message}</div>\n</div>\n'

def rqst_attachments(input):
    sw_joined = False
    pre_attachments = post_attachments = ''

    data_blank = (
        '%s\n'
        '   <div class="fill pull_left"></div>\n'
        '   <div class="body">\n'
        '       <div class="title bold">%s</div>\n'
        '       <div class="status details">%s</div>\n'
        '   </div>'
        '</a>\n'
    )

    human_date = datetime.datetime.fromtimestamp(input['date']).strftime('%y-%m-%d_%H-%M-%S')

    if 'geo' in input:
        sw_joined = True
        html_details = '%s %s' % (input["geo"]["coordinates"]["latitude"], input["geo"]["coordinates"]["longitude"] )

        if 'place' in input["geo"]:
            html_details = '%s (%s)' % (input["geo"]["place"]["title"], html_details )

        pre_attachments = '<div class="media_wrap clearfix">\n%s</div>\n' % ( 
            data_blank % (
                '<a class="media clearfix pull_left block_link media_location">',
                'Местоположение',
                html_details
            ) 
        )

    for i in range(len(input['attachments'])):
        a = input['attachments'][i]
        TYPE = a['type']

        data_fragment = 'missing_attachment = %s' % a
        json_fragment = '' if options.skip_json else f'title="{str_esc(json.dumps(a, indent=10, ensure_ascii=False, sort_keys=True))}"'

        match TYPE:
            case "video":
                # todo: yt-dlp?
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_video" {json_fragment} href="https://vk.com/video{a["video"]["owner_id"]}_{a["video"]["id"]}">',
                    f'{a["video"]["title"]}',
                    f'{datetime.timedelta(seconds=int(a["video"]["duration"]))} | {a["video"]["owner_id"]}_{a["video"]["id"]}'
                )

            case "audio":
                audio_name = str_fix(str_cut(f'{a["audio"]["artist"]} - {a["audio"]["title"]} ({a["audio"]["owner_id"]}_{a["audio"]["id"]})', 80, ''))
                try:
                    href = f'music/{audio_name}.mp3'
                    if options.skip_music:
                        assert False

                    if os.path.exists(href) and not options.rewrite_files:
                        pass
                    else:
                        audio = vk_audio.get_audio_by_id(a["audio"]["owner_id"], a["audio"]["id"])
                        if 'mp3' in audio['url']:
                            mus.rqst_mp3(audio, href)
                        elif 'm3u8' in audio['url']:
                            mus.rqst_m3u8(audio, href)
                        else:
                            assert False
                except (StopIteration, ValueError, AssertionError):
                    href = f'https://m.vk.com/audio{a["audio"]["owner_id"]}_{a["audio"]["id"]}'

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_audio_file" {json_fragment} href="{href}">',
                    audio_name,
                    f'{datetime.timedelta(seconds=int(a["audio"]["duration"]))} | {a["audio"]["owner_id"]}_{a["audio"]["id"]} '
                )

            case "wall":
                href = f'https://vk.com/wall{a["wall"]["to_id"]}_{a["wall"]["id"]}'
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{href}">',
                    'Запись',
                    href
                )

            case "poll":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="https://vk.com/poll{a["poll"]["owner_id"]}_{a["poll"]["id"]}">',
                    'Опрос',
                    f'id{a["poll"]["question"]}'
                )

            case "gift":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{a["gift"]["thumb_256"]}">',
                    'Подарок',
                    f'id{a["gift"]["id"]}'
                )
            
            case "link":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{a["link"]["url"]}">',
                    a['link']['title'],
                    a['link']['caption'] if 'caption' in a['link'] else ''
                )

            case "market":
                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_invoice" {json_fragment} href="https://vk.com/market{a["market"]["owner_id"]}_{a["market"]["id"]}">',
                    a['market']['title'],
                    a['market']['price']['text']
                )

            case "wall_reply":
                if 'deleted' in a['wall_reply']:
                    html_title = 'Комментарий к записи (удалён)'
                    href = ''
                else:
                    html_title = 'Комментарий к записи'
                    href = f'https://vk.com/wall{a["wall_reply"]["owner_id"]}_{a["wall_reply"]["post_id"]}?reply={a["wall_reply"]["id"]}'

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_game" {json_fragment} href="{href}">',
                    html_title,
                    href
                )

            case "doc":
                # what
                namefile = str_fix(str_cut(a['doc']['title'], 80, ''))
                if namefile[-len(a['doc']['ext']):] == a['doc']['ext']:
                    namefile = namefile[:-len(a['doc']['ext']) - 1]

                if options.skip_docs:
                    href = a['doc']['url']
                else:
                    href = f'docs/{namefile}-{i}-{input["conversation_message_id"]}_{human_date}.{a["doc"]["ext"]}'
                    rqst_file(a['doc']['url'], href)

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_file" {json_fragment} href="{href}">',
                    namefile + '.' + a['doc']['ext'],
                    f'{sizeof_fmt(a["doc"]["size"])} ({a["doc"]["owner_id"]}_{a["doc"]["id"]})'
                )

            case "call":
                html_title = 'Исходящий ' if input['from_id'] == a['call']['initiator_id'] else 'Входящий '
                html_title += 'видеозвонок' if a['call']['video'] else 'звонок'

                match a['call']['state']:
                    case "canceled_by_initiator":
                        html_details = 'Отменён'
                    case "canceled_by_receiver":
                        html_details = 'Отклонён'
                    case "reached":
                        html_details = f'Завершен ({datetime.timedelta(seconds=int(a["call"]["duration"]))})'

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_call" {json_fragment}>',
                    html_title,
                    html_details
                )

            case "graffiti":
                if options.skip_graffiti:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{a["graffiti"]["url"]}">',
                        'Граффити',
                        f'{a["graffiti"]["height"]}x{a["graffiti"]["width"]}'
                    )
                else:
                    namefile = f'graffiti-{input["conversation_message_id"]}-{i}_{human_date}.jpg'
                    rqst_file(a["graffiti"]['url'], 'photos/' + namefile)
                    thumb = rqst_thumb('photos/' + namefile, 350, 300)

                    data_fragment = (
                        f'<a class="photo_wrap clearfix pull_left" href="photos/{namefile}">\n'
                        f'<img class="photo" src="{thumb["path"]}" style="width: {thumb["width"]}px; height: {thumb["height"]}px"/></a>'
                    )

            case "audio_message":
                if options.skip_voices:
                    href = a['audio_message']['link_ogg']
                else:
                    href = f'voice_messages/audio-{i}-{input["conversation_message_id"]}_{human_date}.ogg'
                    rqst_file(a['audio_message']['link_ogg'], href)

                data_fragment = data_blank % (
                    f'<a class="media clearfix pull_left block_link media_voice_message" {json_fragment} href="{href}">',
                    'Голосовое сообщение',
                    datetime.timedelta(seconds=int(a["audio_message"]["duration"]))
                )

            case "sticker":
                if options.skip_stickers:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{a["sticker"]["images"][1]["url"]}">',
                        'Стикер',
                        f'id{a["sticker"]["sticker_id"]}'
                    )
                else:
                    rqst_file(a['sticker']['images'][1]['url'], f'userpics/st{a["sticker"]["sticker_id"]}.jpg')

                    data_fragment = (
                        f'<a class="sticker_wrap clearfix pull_left" href="userpics/st{a["sticker"]["sticker_id"]}.jpg">\n'
                        f'<img class="sticker" src="userpics/st{a["sticker"]["sticker_id"]}.jpg" style="width: 128px; height: 128px"/></a>'
                    )

            case "photo":
                p = rqst_photo(a['photo'])

                if options.skip_photos:
                    data_fragment = data_blank % (
                        f'<a class="media clearfix pull_left block_link media_photo" {json_fragment} href="{p["url"]}">',
                        'Фото',
                        f'{p["height"]}x{p["width"]}'
                    )
                else:
                    photo_date = datetime.datetime.fromtimestamp(a['photo']['date']).strftime('%y-%m-%d_%H-%M-%S')
                    namefile = f'ph-{input["conversation_message_id"]}-{i}_{photo_date}.jpg'
                    rqst_file(p['url'], 'photos/' + namefile)
                    thumb = rqst_thumb('photos/' + namefile, 350, 280)

                    data_fragment = (
                        f'<a class="photo_wrap clearfix pull_left" href="photos/{namefile}">\n'
                        f'<img class="photo" src="{thumb["path"]}" style="width: {thumb["width"]}px; height: {thumb["height"]}px"/></a>'
                    )

            case _:
                logger.error(f'missing_attachment: {a}')

        if sw_joined:
            post_attachments += (
                f'<div class="message default clearfix joined">\n'
                f'    <div class="body">{data_fragment}\n'
                f'    </div>\n'
                f'</div>\n'
            )
        else:
            pre_attachments = f'<div class="media_wrap clearfix">\n{data_fragment}</div>\n'
            sw_joined = True

    return (pre_attachments, post_attachments)

def rqst_message(input, forwarded=False):
    global prev_id, prev_date
    fwd_messages = ''
    from_id = rqst_user(input['from_id'])

    # url selection
    if from_id['id'] > 0:
        sender = f'<a href="https://vk.com/id{from_id["id"]}">{from_id["name"]}</a>'
    else:
        sender = f'<a href="https://vk.com/club{str_toplus(from_id["id"])}">{from_id["name"]}</a>'

    # message sending/changing time
    date = datetime.datetime.fromtimestamp(input['date']).strftime('%d/%m/%y %H:%M:%S')
    if 'update_time' in input:
        date = f'({datetime.datetime.fromtimestamp(input["update_time"]).strftime("%H:%M:%S")}) {date}'

    # missing id fix
    if 'conversation_message_id' not in input:
        input["conversation_message_id"] = random.randint(-100,-1)

    # reply message
    if 'reply_message' in input:
        if 'conversation_message_id' in input['reply_message']:
            fwd_messages += rqst_message(input['reply_message'], True)
        else:
            fwd_messages +=  f'<div title="{input["reply_message"]}" class="reply_to details">Нет id пересланного сообщения</div>\n'

    # forwarded messages
    if 'fwd_messages' in input:
        for i in input['fwd_messages']:
            fwd_messages += rqst_message(i, True)

    # requesting attachments
    pre_attachments, post_attachments = rqst_attachments(input)

    # blank selection
    if forwarded:
        blank = fwd_blank
    elif prev_id == from_id['id'] and input['date'] - prev_date < 120:
        blank = jnd_blank
    else:
        prev_date = input['date']
        prev_id = from_id['id']
        blank = def_blank

    return blank % (
        input["conversation_message_id"],
        from_id["id"], from_id["id"],
        sender if forwarded else date,
        date if forwarded else sender,
        fwd_messages,
        str_esc(input["text"], True),
        '<div class="message default"></div>\n' if input["text"] != '' and forwarded and 'fwd_messages' not in input else '' + pre_attachments,
        post_attachments
    )

def makehtml(filename, page, count, target, chat, const_offset_count):
    global progress_str, items_done, offset_count
    for i in range(options.page_number):
        
        while True: #empty check
            chunk = rqst_method(
                'messages.getHistory', 
                {
                    'peer_id': target, 
                    'count': 200, 
                    'extended': 1, 
                    'offset': offset_count * 200
                }
            )
            if len(chunk['items']) != 0 or offset_count < 0:
                break
            else:
                offset_count -= 1

        for msg in reversed(chunk['items']):
            text_append(filename, rqst_message_service(msg) if 'action' in msg else rqst_message(msg))
            items_done += 1

            progress_str = f'[{str_cut(str_fix(chat["title"]), 20)}]'   
            progress_str += f' {fix_val((items_done) / count * 100, 1)}%'
            progress_str += f' {items_done}/{count}'
            progress_str += f' u={len(users)}'
            progress_str += f' html={page + 1}/{count // ( 200 * options.page_number ) + 1}'
            progress_str += f' htmlch={i + 1}/{options.page_number}'
            progress_str += f' allch={const_offset_count - offset_count}/{const_offset_count}'
            
            progress(progress_str)

        offset_count -= 1

def makedump(target):
    global items_done, offset_count, progress_str

    start_time = time.time()
    me = rqst_method('users.get')[0]

    # html header generation
    if target > 2e9:
        r = rqst_method(
            'messages.getChat',
            {'chat_id': target - int(2e9), 'fields': 'photo_200'}
        )

        chat = {
            'title': r['title'],
            'photo': r['photo_200'] if 'photo_200' in r else 'https://vk.com/images/deactivated_200.png'
        }

        admin = rqst_user(r['admin_id'], False)

        info = (
            f'Название: {chat["title"]}\n'
            f'Сохранено в: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'Сидящий: {me["first_name"]} {me["last_name"]} ({me["id"]})\n'
            f'Админ: {admin["name"]} ({admin["id"]})\n'
            f'Юзеров: {r["members_count"]}'
        )

    else:
        r = rqst_user(target, False)
        chat = {
            'title': r['name'],
            'photo': r['photo']
        }

        info = (
            f'Название: {chat["title"]}\n'
            f'Сохранено в: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'Сидящий: {me["first_name"]} {me["last_name"]} ({me["id"]})'
        )

    # directory preparation
    work_dir = f'{(str_cut(str_fix(chat["title"]), 40, ""))} ({target})'
    shutil.copytree('blank', work_dir, dirs_exist_ok=True)
    os.chdir(work_dir)

    for DIR in ['voice_messages', 'music', 'photos/thumbnails', 'docs', 'userpics']:
        os.makedirs(DIR, exist_ok=True)

    rqst_file(chat['photo'], 'userpics/main.jpg')

    # html page creation
    count = rqst_method(
        'messages.getHistory', 
        {
            'peer_id': target, 
            'count': 0
        }
    )['count']
    
    const_offset_count = offset_count = count // 200 + 1
    page_count = count // (200 * options.page_number) + 1

    for page in range(page_count):
        filename = 'messages%s.html' % (page + 1)
        pathlib.Path(filename).unlink(missing_ok=True)

        # header
        text_append(filename, mainfile % ( str_esc(chat["title"]), info, str_esc(chat["title"]) ) )

        # to the previous page
        if page != 0: 
            text_append(
                filename,
                f'\n<a class="pagination block_link" href="messages{page}.html">Предыдущая страница ( {page} / {page_count} )</a>\n'
            )

        # writing messages
        makehtml(filename, page, count, target, chat, const_offset_count)

        # to the next page
        if page + 1 != page_count: 
            text_append(
                filename,
                f'\n<a class="pagination block_link" href="messages{page + 2}.html">Cледующая страница ( {page + 2} / {page_count} )</a>\n'
            )

        # eof
        text_append(filename, '\n            </div>\n        </div>\n    </div>\n</body>\n</html>')

    end_time = fix_val(time.time() - start_time, 0)
    logger.success(f'{chat["title"]} finished in {datetime.timedelta(seconds=int(end_time))}')
    os.chdir('..')

mainfile = (
        '<!DOCTYPE html>\n'
        '<html>\n'
        '\n'
        '<head>\n'
        '    <meta charset="utf-8" />\n'
        '    <title>%s</title>\n'
        '    <meta content="width=device-width, initial-scale=1.0" name="viewport" />\n'
        '    <link href="style.css" rel="stylesheet" />\n'
        '    <script src="script.js" type="text/javascript"></script>\n'
        '</head>\n'
        '\n'
        '<body onload="CheckLocation();">\n'
        '    <div class="page_wrap">\n'
        '        <div class="page_header">\n'
        '            <div class="content">\n'
        '                <div class="text bold" title="%s">%s\n'
        '                    <div class="pull_right userpic_wrap">\n'
        '                        <div class="userpic" style="width: 25px; height: 25px">\n'
        '                            <a class="userpic_link" href="userpics/main.jpg">\n'
        '                                <img class="userpic" src="userpics/main.jpg" style="width: 25px; height: 25px" />\n'
        '                            </a>\n'
        '                        </div>\n'
        '                    </div>\n'
        '                </div>\n'
        '            </div>\n'
        '        </div>\n'
        '        <div class="page_body chat_page">\n'
        '            <div class="history">\n'
)

def_blank = (
        '<div class="message default clearfix" id="message%s">\n'
        '    <div class="pull_left userpic_wrap">\n'
        '        <div class="userpic" style="width: 42px; height: 42px">\n'
        '            <a class="userpic_link" href="userpics/id%s.jpg">\n'
        '                <img class="userpic" src="userpics/id%s.jpg" style="width: 42px; height: 42px" />\n'
        '            </a>\n'
        '        </div>\n'
        '    </div>\n'
        '    <div class="body">\n'
        '        <div class="pull_right date details">%s</div>\n'
        '        <div class="from_name">%s</div>\n'
        '%s' # reply_message, fwd_messages
        '        <div class="text">\n%s\n</div>\n'
        '%s' # fwd_text_prefix, pre_attachments
        '    </div>\n'
        '</div>\n'
        '%s\n' # post_attachments
)

fwd_blank = (
        '<div class="pull_left forwarded userpic_wrap">\n'
        '    <!-- start-fwd-id=%s" -->\n'
        '    <div class="userpic" style="width: 42px; height: 42px">\n'
        '        <a class="userpic_link" href="userpics/id%s.jpg">\n'
        '            <img class="userpic" src="userpics/id%s.jpg" style="width: 42px; height: 42px" /></a>\n'
        '    </div>\n'
        '</div>\n'
        '<div class="forwarded body">\n'
        '    <div class="from_name">\n'
        '        %s<span class="details"> %s</span>\n'
        '    </div>\n'
        '%s' # reply_message, fwd_messages
        '    <div class="text">\n%s</div>\n'
        '%s' # fwd_text_prefix, pre_attachments
        '</div>\n'
        '%s' # post_attachments
        '<!-- end-fwd -->\n'
)

jnd_blank = (
        '<div class="message default clearfix joined" id="%s">\n'
        '    <!-- joined-id%s-id%s" -->\n'
        '    <div class="body">\n'
        '        <div class="pull_right date details">%s</div>\n'
        '    <!-- joined-name %s" -->\n'
        '%s' # reply_message, fwd_messages
        '        <div class="text">\n%s</div>\n'
        '%s' # fwd_text_prefix, pre_attachments
        '    </div>\n'
        '</div>\n'
        '%s\n' # post_attachments
)

if __name__ == "__main__":
    # loguru custom preset
    logger.remove(0)
    logger.add(
        sys.stderr,
        backtrace = True,
        diagnose = True,
        format = "<level>[{time:HH:mm:ss}]</level> {message}",
        colorize = True,
        level = 5
    )

    def rqst_dialogs():
        conversations = []
        count = rqst_method('messages.getConversations', {'count': 0})['count']

        for offset in range(count // 200 + 1):
            chunk = rqst_method(
                'messages.getConversations',
                {
                    'count': 200,
                    'extended': 1,
                    'offset': offset * 200
                }
            )

            for item in chunk['items']:
                id = item['conversation']['peer']['id']

                if id not in conversations:
                    conversations.append(id)

        logger.info('loaded %s dialogs!' % len(conversations))
        return conversations

    if not options.login_info:
        options.login_info = f'{input("Login: ")}:{input("Pass: ")}'

    if ':' in options.login_info:
        lp = options.login_info.split(':')

        vk_session = VkApi(lp[0], lp[1], app_id=6287487)
        try:
            vk_session.auth()
            vk_audio = audio.VkAudio(vk_session)

        except AuthError as ex:
            logger.error('autechre error: ' + str(ex))
            sys.exit()

    elif len(options.login_info) >= 85:
        vk_session = VkApi(token=options.login_info)
        logger.warning('token used, music will not dumped')
        options.skip_music = True

    else:
        logger.error('login info is invalid!')
        sys.exit()

    me = rqst_method('users.get')[0]
    me_fl = str_fix(me["first_name"] + " " + me["last_name"])
    logger.info(f'{me_fl} ({me["id"]})')
    logger.add('%s.txt' % me_fl,
        backtrace = True,
        diagnose = True,
        format = "{time:YYYY-MM-DD HH:mm:ss.SSS zz} | <level>{level: <8}</level> | L {line: >4} ({file}): {message}",
        colorize = False,
        level = 5
    )

    conversations = rqst_dialogs()

    if len(arguments):
        for i in arguments:
            users = {}
            prev_id = 0
            prev_date = 0
            progress_str = ''

            if i == 'self':
                makedump(rqst_method('users.get')[0]['id'])

            elif i[:+1] == '@':
                makedump(2000000000 + int(i[1:]))

            else:
                work = None

                if isinstance(work, int):
                    work = abs(work)

                check_group = rqst_method('groups.getById', {'group_ids': i})
                check_user = rqst_method('users.get', {'user_ids': i})

                # сhecking for id in dialogs (can be disabled)
                if check_group != None and -check_group[0]['id'] in conversations:
                    work = str_tominus(check_group[0]['id'])
                if check_user != None and check_user[0]['id'] in conversations:
                    work = str_toplus(check_user[0]['id'])

                if work == None:
                    logger.error(f'{i} is invalid')
                else:
                    makedump(int(work))
    else: # no args = dump all
        start_time = time.time()

        me_dir = f'Диалоги {str_fix(me["first_name"] + " " + me["last_name"])} ({me["id"]})'
        os.makedirs(me_dir, exist_ok=True)
        if not os.path.exists(f'{me_dir}/blank'):
            shutil.copytree('blank', f'{me_dir}/blank')
        os.chdir(me_dir)

        for i in range(len(conversations)):
            users = {}
            prev_id = items_done = prev_date = 0
            progress_str = ''
            makedump(conversations[i])

        end_time = fix_val(time.time() - start_time, 0)
        logger.success(f'all saved in: {datetime.timedelta(seconds=int(end_time))}')

        shutil.rmtree('blank')
        sys.exit()
