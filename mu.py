#!/usr/bin/env python3
import os
import sys
import requests
import time
import re
import shutil
import datetime
import math
import threading
import glob

import ffmpeg, optparse
from loguru import logger

from vk_api import VkApi
from vk_api import audio
from vk_api.exceptions import AuthError, VkApiError

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

import io
import concurrent.futures 

m3u8_threads = 3

def str_cut(string, letters = 100, postfix='...'):
    return string[:letters] + (string[letters:] and postfix)

def str_fix(string, letters = 100):
    return str_cut(re.sub(r'[/\\?%*\-\[\]{}:|"<>]', '', string), letters)

def fix_val(number, digits):
    return f'{number:.{digits}f}'

def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0
    return "%3.1f %s" % (num, 'TB')

def rqst_method(method, values={}):
    while True:
        try:
            request = vk_session.method(method, values)
            return request
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
                logger.error(f'execption in method \'{method}\': {ex_str}   ')
                time.sleep(10)

def rqst_str(url):
    with requests.get(url, headers={"Accept-Encoding": "identity"}) as request:
        if request:
            return request.content
        logger.warning(f'{url} ({request.status_code})')

def rqst_mp3(track, final_name=''):
    block_size = 1024 # 1 Kibibyte

    desc = f'{str_fix(track["artist"], 50)} - {str_fix(track["title"], 50)}'
    if not final_name:
        final_name = str_cut(f'{str_fix(track["artist"])} - {str_fix(track["title"])}', 100, '') + ' (' + str(track['id']) + ').mp3'

    if os.path.exists(f'{track["id"]}.tmp'):
        os.remove(f'{track["id"]}.tmp')
        if os.path.exists(final_name):
            os.remove(final_name)

    if glob.glob(f'**/{final_name}', recursive=True):
        logger.warning(f'{desc}: already exists, skipping.')
        return

    response = requests.get(track["url"], stream=True)
    if not response:
        logger.error(f'{desc}: not responding ({response.status_code}).')
        return

    dlen = int(response.headers.get('Content-Length', '0')) or None
    size = 0
    with open(f'{track["id"]}.tmp', 'wb', buffering = block_size) as file:
        for data in response.iter_content(chunk_size = block_size):
            try:
                file.write(data)
                size += len(data)

                percent = fix_val(
                    ( math.ceil(dlen / block_size) / math.ceil(size / block_size) ) * 100, 2
                )

                print(f'{desc}: {percent}% {sizeof_fmt(dlen)} / {sizeof_fmt(size)}', end='\r')

            except Exception as ex:
                logger.error(f'{os.path.basename(dir)} ({str(ex)})')
                time.sleep(5)
    response.close()

    (
        ffmpeg
        .input(f'{track["id"]}.tmp')
        .output(final_name, acodec='copy', **{ 
            'metadata':f'title={track["title"]}', 
            'metadata:':f'artist={track["artist"]}' 
        })
        .run(quiet=True)
    )

    os.remove(f'{track["id"]}.tmp')

    logger.success(f'{desc} {sizeof_fmt(os.path.getsize(final_name))}        ')

# Zerogoki00/vk-audio-downloader
def rqst_m3u8(track, final_name=''):
    def rqst_decryptor(k_url):
        k = rqst_str(k_url)
        c = Cipher(
            algorithms.AES(k), 
            modes.CBC(b'\x00' * 16), 
            backend=default_backend()
        )

        return c.decryptor()

    def rqst_block(block, key_url):
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

    desc = f'{str_fix(track["artist"], 50)} - {str_fix(track["title"], 50)}'
    if not final_name:
        final_name = str_cut(f'{str_fix(track["artist"])} - {str_fix(track["title"])}', 100, '') + ' (' + str(track['id']) + ').mp3'

    if glob.glob(f'**/{final_name}', recursive=True):
        logger.info(f'{desc}: already exists, skipping.')
        return
    
    # playlist
    blocks = [b for b in rqst_str(track['url']).decode("utf-8").split("#EXT-X-KEY") if "#EXTINF" in b] 
    if not blocks:
        logger.error(f'{desc}: internal error, skipping.')
        return

    key_url = re.findall(r':METHOD=AES-128,URI="(\S*)"', blocks[0])[0]

    # https://stackoverflow.com/a/63514035
    with concurrent.futures.ThreadPoolExecutor(max_workers=m3u8_threads) as executor:
        future_to_blk = {
            executor.submit(rqst_block, blk, key_url): (i, blk) for i, blk in enumerate(blocks)
        }
        futures = {}

        for future in concurrent.futures.as_completed(future_to_blk):
            i, blk = future_to_blk[future]
            futures[i] = blk, future

            percent = fix_val(
                ( len(futures) / (len(blocks) + 1) ) * 100, 2
            )
            print(f'{desc}: {percent}% {len(blocks)} / {len(futures)}', end='\r')
            
        for i in range(len(futures)):
            blk, future = futures[i]
            try:
                with open(f'{track["id"]}-Frag{i}.ts', "wb") as file:
                    file.write(future.result())

            except Exception as ex:
                logger.error('%r generated an exception: %s' % (blk, ex))

    if os.path.exists(f'{track["id"]}.tmp'):
        os.remove(f'{track["id"]}.tmp')

    with open(f'{track["id"]}.tmp', "ab") as out_file:
        for i in range(len(blocks)):
            with open(f'{track["id"]}-Frag{i}.ts', "rb") as in_file:
                out_file.write(in_file.read())

    (
        ffmpeg
        .input(f'{track["id"]}.tmp')
        .output(final_name, acodec='copy', **{ 
            'metadata':f'title={track["title"]}', 
            'metadata:':f'artist={track["artist"]}' 
        })
        .run(quiet=True)
    )

    os.remove(f'{track["id"]}.tmp')
    for i in range(len(blocks)):
        os.remove(f'{track["id"]}-Frag{i}.ts')

    logger.success(f'{desc} {sizeof_fmt(os.path.getsize(final_name))}        ')

if __name__ == '__main__':
    def rqst_id(id):
        def str_toplus(string):
            string = str(string)
            return string[1:] if string[0] == '-' else string

        def str_tominus(string):
            string = str(string)
            return '-' + string if string[0] != '-' else string

        id = str_toplus(id)

        check_group = rqst_method('groups.getById', {'group_ids': id})
        check_user = rqst_method('users.get', {'user_ids': id})

        if check_user != None: 
            return {
                'id': str_toplus(check_user[0]['id']), 
                'name': f'{check_user[0]["first_name"]} {check_user[0]["last_name"]}'
            }
        elif check_group != None:
            return {
                'id': str_tominus(check_group[0]['id']), 
                'name': check_group[0]["name"]
            }
        else:
            return False

    def rqst_album(album):
        path = re.sub(r'[/\\?%*\[\]:|"<>]', '', f'{str_cut(album["title"])} ({album["id"]})') # w/o "-"
        os.makedirs(path, exist_ok=True)
        os.chdir(path)
        
        for track in vk_audio.get_iter(owner_id = album['owner_id'], album_id = album['id'], access_hash = album['access_hash']):
            if 'm3u8' in track['url']:
                rqst_m3u8(track)
            elif 'mp3' in track['url']:
                rqst_mp3(track)

        os.chdir('..')

    logger.remove(0)
    logger.add(
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
    parser.add_option('-m', '--skip-music', dest='skip_music', action='store_true', help='Skip playlists')
    parser.add_option('-a', '--skip-albums', dest='skip_albums', action='store_true', help='Skip music')

    options, arguments = parser.parse_args()

    m3u8_threads = options.m3u8_threads
    if ":" not in options.login_info:
        options.login_info = f'{input("Login: ")}:{input("Pass: ")}'

    lp = options.login_info.split(':')
    vk_session = VkApi(lp[0], lp[1], app_id=2685278, config_filename='vkconfig.json')
    try:
        vk_session.auth()
        os.remove('vkconfig.json')
        vk_audio = audio.VkAudio(vk_session)
        logger.info('login success')
    except AuthError as ex:
        logger.error('autechre error: ' + str(ex), 1)
        sys.exit()

    if not arguments:
        logger.info('no arguments, self-dumping')
        arguments.append(str(rqst_method('users.get')[0]['id']))

    for i, argument in enumerate(arguments, start=1):
        if argument[:+8] == 'https://': 
            argument = argument[8:]

        if argument[:+7] == 'vk.com/': 
            argument = argument[7:]

        if argument[:+6] == 'music/':
            argument = argument[6:]

        if argument[:+9] == 'playlist/':
            argument = argument[9:]

            if argument.count('_') > 1:
                owner_id, album_id, access_hash = argument.split('_')

            else:
                owner_id, album_id = argument.split('_')
                access_hash = ''
                
            rqst_album({
                "id": album_id, 
                "owner_id": owner_id, 
                "access_hash": access_hash, 
                "title": access_hash # fixme?
            })
            continue

        if argument[:+5] in ['audio', '[[aud']: # vkopt
            if argument[-2:] == ']]': 
                argument = argument[:-2]

            if argument[:+2] == '[[': 
                argument = argument[2:]

            if argument[:+5] == 'audio': 
                argument = argument[5:]

            owner_id, album_id = argument.split('_')
            track = vk_audio.get_audio_by_id(owner_id, album_id)

            if 'm3u8' in track['url']:
                rqst_m3u8(track)
            elif 'mp3' in track['url']:
                rqst_mp3(track)
                
            continue

        target = rqst_id(argument)
        if not target:
            logger.error(f'targets: {argument} invalid.')
            continue

        logger.info(f'targets: [{i}/{len(arguments)}] {target["name"]} is downloading. ')

        path = str_fix(f'{target["name"]} ({target["id"]})')
        os.makedirs(path, exist_ok=True)
        os.chdir(path)

        if not options.skip_albums:
            logger.info(f'looking for albums...')
            albums_list = vk_audio.get_albums(owner_id = target['id'])

            for i, album in enumerate(albums_list, start=1):
                logger.info(f'albums: [{i}/{len(albums_list)}] {album["title"]} is downloading. ')
                rqst_album(album)
                print('')

        if not options.skip_music:
            logger.info(f'downloading tracks...')
            for track in vk_audio.get_iter(owner_id = target['id']):
                print(track)
                if 'm3u8' in track['url']:
                    rqst_m3u8(track)
                elif 'mp3' in track['url']:
                    rqst_mp3(track)
    
        os.chdir('..')  
