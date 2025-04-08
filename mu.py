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

from loguru import logger as log
tr, warn, inf, err, ok = (log.trace, log.warning, log.info, log.error, log.success)

from vk_api import VkApi
from vk_api import audio
from vk_api.exceptions import AuthError

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from utils import (
    sizeof_fmt,
    html_fmt,
    fix_val,
    str_toplus,
    str_tominus,
    str_fix,
    str_cut,
    text_append,
    delete_file
)

m3u8_threads = 3

def progress(string):
    print(" " * os.get_terminal_size().columns, end = '\r')
    print(string , end = '\r')

def rqst_method(method, values={}):
    while True:
        try:
            r = vk_session.method(method, values)
            return r
            
        except Exception as e:
            e = str(e)

            # invalid login/pass
            if '[5] User authorization failed:' in e:
                err('autechre error: ' + e[31:])
                sys.exit()

            # non-existing user
            if 'Invalid user id' in e:
                return None

            # non-existing group
            if 'group_ids is undefined' in e:
                return None

            # non-existing chat
            if 'no access to this chat' in e:
                return None

            # idk
            if 'Internal server error' in e:
                warn('internal catched, waiting...   ')
                time.sleep(100)

            else:
                err(f'execption in \'{method}\': {e}, values={values}   ')
                time.sleep(10)

def rqst_str(url):
    with requests.get(url, headers={"Accept-Encoding": "identity"}) as request:
        if request:
            return request.content
        warn(f'{url} ({request.status_code})')

def rqst_multiple(track, final_name=''):
    # https://github.com/Zerogoki00/vk-audio-downloader
    def m3u8_block(block, key_url):
        def rqst_decryptor(u):
            k = rqst_str(u)
            c = Cipher(
                algorithms.AES(k), 
                modes.CBC(b'\x00' * 16), 
                backend=default_backend()
            )

            return c.decryptor()

        segments = []
        segment_urls = re.findall(r'#EXTINF:\d+\.\d{3},\s(\S*)', block)

        for s_url in segment_urls:
            segments.append(rqst_str(track['url'][:track['url'].rfind("/")] + "/" + s_url)) # base_url

        if "METHOD=AES-128" in block:
            segment_key_url = re.findall(r':METHOD=AES-128,URI="(\S*)"', block)[0]

            decryptor = rqst_decryptor(key_url)
            if segment_key_url != key_url:
                decryptor = rqst_decryptor(segment_key_url)

            for j, seg in enumerate(segments):
                segments[j] = decryptor.update(seg)

        return b''.join(segments) # finished block

    block_size = 1024 # 1 Kibibyte

    id_tmp = '%s.tmp' % track["id"]
    name = "%s - %s" % (str_cut(track["artist"], 100, ''), str_cut(track["title"], 100, ''))
    desc = "%s - %s" % (str_cut(track["artist"], 50, ''), str_cut(track["title"], 50, ''))

    if not final_name:
        final_name = "%s (%s).mp3" % (name, track['id'])
        final_name = str_fix(final_name, 0) # ntfs escaping

    glob_esc = {"[": "[[]", ']': "[]]"}
    glob_fn = "".join(glob_esc.get(c, c) for c in final_name)
    if glob('**/%s' % glob_fn, recursive=True):
        warn("exists | %s " % desc)
        return

    if '.mp3' in track["url"]:
        with requests.get(track["url"], stream=True, timeout=10) as r:
            if not r:
                m = '%s: bad r (%s)' % (desc, r.status_code)
                err(m)
                return 

            cl = int(r.headers.get('Content-Length', '0')) or None
            dw_total = 0
            with open("mu.ts", 'wb', buffering = block_size) as file:
                for data in r.iter_content(chunk_size = block_size):
                    try:
                        file.write(data)
                        dw_total += len(data)

                        percent = (math.ceil(cl / block_size) / math.ceil(dw_total / block_size)) * 100
                        percent = fix_val(percent, 2)

                        progress(f'{desc}: {percent}% {sizeof_fmt(cl)} / {sizeof_fmt(dw_total)}')

                    except Exception as e:
                        m = '%s (%s)' % (os.path.basename(dir), str(e))
                        err(m)
                        time.sleep(5)

    elif '.m3u8' in track["url"]:
        # playlist
        blocks = [b for b in rqst_str(track['url']).decode("utf-8").split("#EXT-X-KEY") if "#EXTINF" in b] 
        if not blocks:
            err('internal | %s' % desc)
            return

        key_url = re.findall(r':METHOD=AES-128,URI="(\S*)"', blocks[0])[0]

        # https://stackoverflow.com/a/63514035
        with concurrent.futures.ThreadPoolExecutor(max_workers=m3u8_threads) as executor:
            future_to_blk = {
                executor.submit(m3u8_block, blk, key_url): (i, blk) for i, blk in enumerate(blocks)
            }
            futures = {}

            for future in concurrent.futures.as_completed(future_to_blk):
                i, blk = future_to_blk[future]
                futures[i] = blk, future

                percent = (len(futures) / (len(blocks))) * 100
                percent = fix_val(percent, 2)

                print(f'{desc}: {percent}% {len(blocks)} / {len(futures)}', end='\r')
                
            for i, _ in enumerate(futures):
                blk, future = futures[i]
                try:
                    with open('frag%s.ts' % i, "wb") as file:
                        file.write(future.result())

                except Exception as e:
                    err('%r ex: %s' % (blk, e))

        # merging *.ts files in one
        with open("mu.ts", "wb") as ts:
            for i, _ in enumerate(blocks):
                fn = 'frag%s.ts' % i
                with open(fn, "rb") as frg:
                    ts.write(frg.read())

                delete_file(fn) # saving disk space!
                print(f'{desc}: dd {i} / {len(blocks)}          ', end='\r')
    else:
        err("nani | %s" % track)

    metadata = { 
        'metadata:g:1:':f'TPE1={track["artist"]}',
        'metadata:g:2':f'TIT2={track["title"]}', 
        'metadata:g:3':f'COMM={track["owner_id"]}_{track["id"]}'
    }

    p = ffmpeg.input("mu.ts").output("mu.mp3", acodec='copy', **metadata)
    #print(ffmpeg.get_args(p))
    
    print(f'{desc}: merging...          ', end='\r')
    p.run(quiet=True)
    
    os.rename("mu.mp3", final_name)
    delete_file("mu.ts")

    size = sizeof_fmt(os.path.getsize(final_name))
    ok("%s (%s)" % (desc, size))

if __name__ == '__main__':
    def rqst_id(id):
        id = str_toplus(id)

        check_group = rqst_method('groups.getById', {'group_ids': id})
        check_user = rqst_method('users.get', {'user_ids': id})

        if check_user: 
            return {
                'id': str_toplus(check_user[0]['id']), 
                'name': f'{check_user[0]["first_name"]} {check_user[0]["last_name"]}'
            }
        elif check_group:
            return {
                'id': str_tominus(check_group[0]['id']), 
                'name': check_group[0]["name"]
            }
        else:
            return False

    def rqst_album(album):
        path = '%s - (%s)' % (str_cut(album["title"], 200), album["id"]) # w/o "-" ???
        path = str_fix(path, 0)
        os.makedirs(path, exist_ok=True)
        os.chdir(path)
        
        for track in vk_audio.get_iter(
                owner_id = album['owner_id'], 
                album_id = album['id'], 
                access_hash = album['access_hash']
            ):
            rqst_multiple(track)

        os.chdir('..')

    log.remove(0)
    log.add(
        sys.stderr, 
        backtrace = True, 
        diagnose = True, 
        format = "<level>[{time:HH:mm:ss}]</level> {message}", 
        colorize = True,
        level = 5
    )

    #parse args
    parser = optparse.OptionParser()
    parser.add_option('-l', '--login', dest='login_info', default='', help='Login info (login:pass)')
    parser.add_option('-r', '--rewrite', dest='rewrite_files', action='store_true', help='Force rewriting files')
    parser.add_option('-t', '--threads', dest='m3u8_threads', type=int, default='3', help='m3u8 threads')
    parser.add_option('-m', '--skip-music', dest='skip_music', action='store_true', help='Skip music')
    parser.add_option('-a', '--skip-albums', dest='skip_albums', action='store_true', help='Skip albums/playlists')
    options, arguments = parser.parse_args()

    m3u8_threads = options.m3u8_threads

    if ":" not in options.login_info:
        options.login_info = f'{input("Login: ")}:{input("Pass: ")}'

    lp = options.login_info.split(':')
    vk_session = VkApi(lp[0], lp[1], app_id=2685278)

    try:
        vk_session.auth()
        vk_audio = audio.VkAudio(vk_session)

    except AuthError as e:
        err('autechre error: %s' % str(e))
        sys.exit(1)

    if not arguments:
        me = rqst_method('users.get')[0]['id']
        arguments.append(str(me))

    for i, arg in enumerate(arguments, start=1):
        if arg.startswith('https://'): 
            arg = arg[8:]
        if arg.startswith('vk.com/'): 
            arg = arg[7:]
        if arg.startswith('music/'):
            arg = arg[6:]
        if arg.startswith('playlist/'):
            arg = arg[9:]

            if arg.count('_') > 1:
                owner_id, album_id, access_hash = arg.split('_')
            else:
                owner_id, album_id = arg.split('_')
                access_hash = ''
                
            rqst_album(
                {
                    "id": album_id, 
                    "owner_id": owner_id, 
                    "access_hash": access_hash, 
                    "title": access_hash # fixme?
                }
            )

            continue

        if arg[:+5] in ['audio', '[[aud']: # vkopt
            if arg.startswith('[['): 
                arg = arg[2:]
            if arg.endswith(']]'): 
                arg = arg[:-2]
            if arg.startswith('audio'): 
                arg = arg[5:]

            owner_id, album_id = arg.split('_')
            track = vk_audio.get_audio_by_id(owner_id, album_id)

            rqst_multiple(track)
                
            continue

        target = rqst_id(arg)
        if not target:
            err('targets: %s invalid.' % arg)
            continue

        inf(f'targets: [{i}/{len(arguments)}] {target["name"]} is downloading. ')

        path = '%s (%s)' % (target["name"], target["id"])
        path = str_fix(path)
        
        os.makedirs(path, exist_ok=True)
        os.chdir(path)

        if not options.skip_albums:
            inf(f'looking for albums...')
            albums_list = vk_audio.get_albums(owner_id = target['id'])

            for i, album in enumerate(albums_list, start=1):
                inf(f'albums: [{i}/{len(albums_list)}] {album["title"]} is downloading. ')
                rqst_album(album)
                print('')

        if not options.skip_music:
            inf(f'downloading tracks...')
            for track in vk_audio.get_iter(owner_id = target['id']):
                rqst_multiple(track)
    
        os.chdir('..')  
