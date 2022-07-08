#!/usr/bin/env python3
import time, threading, sys, os, json, datetime, requests, optparse, re, hashlib, logging
from vk_api import VkApi
from vk_api.exceptions import AuthError, VkApiError

login_info = '' # access token or "login:pass"

progress_left = 0
progress_all = 0

def date_time(format):
    return datetime.datetime.now().strftime(format)

def str_toplus(string):
    string = str(string)
    return string[1:] if string[0] == '-' else string

def str_tominus(string):
    string = str(string)
    return '-' + string if string[0] != '-' else string

def str_fix(string):
    return re.sub(r'[/\\\'?%*:|"<>]', '', string)

def str_cut(string, letters=20, postfix='...'):
    return string[:letters] + (string[letters:] and postfix)

def val_fix(number, digits):
    return f'{number:.{digits}f}'

def rqst_filename(numbers, url):
    if url.find('?') != -1: 
        url = url[:url.find('?')]
    id = '0' * (len(str(progress_all)) - len(str(numbers))) + str(numbers) 
    return f'{id}_{os.path.basename(url)}'

def progress_upd(all, left, show):
    progress = float(left / all)
    block = int(round(7 * progress))
    print(f'{show}: [{"#" * block + "-" * (7 - block)}] ({all} / {left}) {val_fix(progress * 100, 2)}%', end = '\r')

def rqst_method(method, values={}):
    while True:
        try:
            return vk.method(method, values)
        except Exception as ex:
            ex_str = str(ex)

            # invalid login/pass
            if '[5]' in ex_str:
                logging.error('autechre error: ' + ex_str[31:])
                sys.exit()

            # invalid id / no albums in group
            elif re.findall('\[100\]|\[113\]|group photos are disabled', ex_str):
                logging.error(f'no id / no albums: {values}, {str(ex)}')
                return None

            # no access to albums
            elif re.findall('\[18\]|\[30\]|\[15\]|\[200\]', ex_str):
                logging.error(f'no access: {values}, {str(ex)}')
                return False

            # occurs with frequent requests
            elif 'server' in ex_str:
                logging.error(f'internal catched, waiting...   ')
                time.sleep(60)

            else:
                logging.error(f'\'{method}\': {ex_str}')
                time.sleep(5)

def download_thread(offset, images, progress_show):
    def is_exist(filename, dir): # what
        if filename in dir:
            return True
        for file in dir:
            if file[-3:] != 'txt' and filename[len(str(progress_all)) + 1:-4] in dir: # 999_ 'qwerty' .jpg
                return True
        return False

    global progress_left, progress_all
    dir_list = os.listdir()
    for i in range(len(images)):
        if int((i + offset) % options.threads_count) == 1 or options.threads_count < 2:
            picture = images[str(i)]['picture']
            text = images[str(i)]['text']
            date = images[str(i)]['date']
            filename = rqst_filename(i, picture)
            output = None
            #likes = images[str(i)]['likes']
            #comments = images[str(i)]['comments'] 
            #tags = images[str(i)]['tags']
            #reposts = images[str(i)]['reposts']
            
            if not is_exist(filename, dir_list) or options.rewrite_files: 
                while True:
                    try:
                        with requests.get(picture, stream=True) as request:
                            if request:
                                output = request.content
                            else:
                                logging.error(f'{request.status_code} {filename}')
                        break
                    except Exception as ex:
                        logging.warning(f'{filename}: {str(ex)}    ')
                        time.sleep(5)

                if text:
                    with open(f'{filename}_description.txt', 'w') as file:
                        file.write(text + '\n')
                        if date:
                            os.utime(f'{filename}_description.txt', (date, date))

                if output:
                    with open(filename, 'wb') as file:
                        file.write(output)
                        if date:
                            os.utime(filename, (date, date))

            elif is_exist(filename, dir_list) and date:
                os.utime(filename, (date, date))
                if text:
                    os.utime(f'{filename}_description.txt', (date, date))

            progress_left += 1
            progress_upd(progress_all, progress_left, progress_show)

def get_json(filename):
    start_time = time.time()
    with open(filename) as file:
        i_json = json.load(file)

    global progress_all, progress_left
    progress_all = len(i_json)
    progress_left = 0

    # start threads
    for i in range(options.threads_count):
        threading.Thread(target=download_thread, args=[i, i_json, filename]).start()

    # waiting for end
    while threading.active_count() > 1:
        time.sleep(0.01)

    # printing time and exit from dir
    end_time = val_fix(time.time() - start_time, 0)
    print(f'{filename}: [{datetime.timedelta(seconds=int(end_time))}]')

def get_album(t_info, input_str, prefix):
    def add_items(json):
        def dict_append(url, item):
            images[str(len(images))] = {
                'picture': url, 
                'text': item['text'] if item['text'] else None, 
                'date': item['date'] if 'date' in item else None, 
                'likes': item['likes']['count'] if item['likes'] else None,
                'comments': item['comments']['count'] if 'comments' in item else None,
                'tags': item['tags']['count'] if item['tags'] else None,
                'reposts': item['reposts']['count'] if item['reposts'] else None
            }

        def rqst_size(input):
            photo = ''
            current = 0
            for size in input['sizes']:
                if size['type'] == 'w':
                    photo = size['url']
                    break
                elif size['type'] == 's' and current < 1:
                    current = 1
                    photo = size['url']
                elif size['type'] == 'm' and current < 2:
                    current = 2
                    photo = size['url']
                elif size['type'] == 'x' and current < 3:
                    current = 3
                    photo = size['url']
                elif size['type'] == 'y' and current < 4:
                    current = 4
                    photo = size['url']
                elif size['type'] == 'z' and current < 5:
                    current = 5
                    photo = size['url']
            return photo

        for i, item in enumerate(json['items']):
            url = rqst_size(item)
            if url:
                dict_append(url, item)
            else:
                logging.info(f'missing item {i}: {item}')
                
            '''
            rip v5.67
            for j in [2560, 1280, 807, 604, 130, 75]:
                if f'photo_{j}' in json['response']['items'][i]:
                    dict_append(json['response']['items'][i][f'photo_{j}'], text, date)
                    break
            '''

    global progress_all, progress_left
    start_time = time.time()
    progress_left = 0
    images = {}

    album_name = 'album' + input_str
    owner_id, album_id = input_str.split('_')
    
    title = ''
    if album_id == '0':
        album_id = 'profile'
        title = 'Фотографии со страницы '
    if album_id == '00':
        album_id = 'wall'
        title = 'Фотографии на стене '
    if album_id == '000':
        album_id = 'saved'
        title = 'Сохранённые фотографии '
    if album_id == '-9000':
        album_id = 'tagged'
        title = 'Фотографии с отметками '
    
    if '-' in owner_id:
        title += 'сообщества ' + t_info[0]['name']
    else:
        title += t_info[0]['first_name'] + ' ' + t_info[0]['last_name']

    album = rqst_method('photos.getAlbums', {'owner_id': owner_id, 'album_ids': album_id, 'need_system': 0})

    if '-' in owner_id and album == None:
        title = t_info[0]['name']
    elif album_id not in ['wall', 'profile', 'saved', 'tagged']:
        if 'title' in album['items'][0]:
            title = album['items'][0]['title']    
            prefix += f'({str_cut(title)}) | '

    photos = rqst_method(
            'photos.getUserPhotos' if album_id == 'tagged' else 'photos.get', 
            {
                'owner_id': owner_id, 
                'album_id': album_id, 
                'count': '1000', 
                'extended': True, 
                'rev': 0
            }
        )

    progress_all = count = photos['count']
    progress_show = prefix + album_name

    # dump img data
    if count == 0:
        print(progress_show, 'is empty.')
        return
    elif count < 1000:
        add_items(photos)
    else:
        offset_count = count // 1000 + 1
        for i in range(offset_count):
            photos = rqst_method(
                'photos.getUserPhotos' if album_id == 'tagged' else 'photos.get',
                {
                    'owner_id': int(owner_id), 
                    'album_id': album_id,
                    'offset': i * 1000, 
                    'count': '1000', 
                    'extended': True, 
                    'rev': 0
                }
            )

            print(f'{progress_show}: ({offset_count} / {i + 1} / {len(photos["items"])})    ', end='\r')
            add_items(photos)

    # creating folders
    directory = str_cut(f'{str_fix(title)} ({album_id})', 100)
    os.makedirs(directory, exist_ok=True)
    os.chdir(directory)
              
    # album info
    if album_id not in ['wall', 'profile', 'saved', 'tagged'] and 'error' not in album:
        saved = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        created = datetime.datetime.fromtimestamp(album['items'][0]['created']).strftime('%Y-%m-%d %H:%M:%S')
        updated = datetime.datetime.fromtimestamp(album['items'][0]['updated']).strftime('%Y-%m-%d %H:%M:%S')
        description = 'id: %d\nthumb_id: %d\nowner_id: %d\ntitle: %s\ndescription: %s\ncreated: %s\nupdated: %s\nsaved: %s\nphotos: %d\n' % (
            album['items'][0]['id'],
            album['items'][0]['thumb_id'],
            album['items'][0]['owner_id'],
            album['items'][0]['title'],
            album['items'][0]['description'], 
            created, updated, saved,
            album['items'][0]['size']
        )

        with open(f'{album_name}_description.txt', 'w') as file:
            file.write(description)

    # saving json with images
    hash_prefix = hashlib.md5(str(images).encode('utf-8')).hexdigest()[:10]
    with open(f'{hash_prefix}_{album_name}_list.txt', 'w') as file:
        json.dump(images, file, indent=2, sort_keys=True)

    # generate file for aria2c
    #with open(f'{hash_prefix}_{album_name}_aria2c.txt', 'w') as file:
    #    for i in range(len(images)):
    #        file.write(f"{images[str(i)]['picture']}\n    out={rqst_filename(i, images[str(i)]['picture'])}\n")
        
    # start threads 
    if not options.simulate:
        # start threads
        for i in range(options.threads_count):
            threading.Thread(target=download_thread, args=[i, images, progress_show]).start()

        # waiting for end
        while threading.active_count() > 1:
            time.sleep(0.01)

    # printing time and exit from dir
    end_time = val_fix(time.time() - start_time, 0)
    print(f'{progress_show}: [{datetime.timedelta(seconds=int(end_time))}] ({progress_all} / {progress_all})')
    os.chdir('..')

def parse_link(i_work, num_seq=0, num_all=0, sw_steal=True): # input workstr, sequence str
    logging.info(f'in_link: {i_work}')
    # clean link
    if i_work[-6:] in ['?rev=1', '?rev=0']: i_work = i_work[:-6]
    if i_work[:+8] == 'https://': i_work = i_work[8:]
    if i_work[:+7] == 'vk.com/': i_work = i_work[7:]

    album_id = ''
    if re.findall('public|albums', i_work[:6]):
        i_work = i_work[6:]
    elif i_work[:+5] == 'album':
        # dump one album 1/2
        i_work = i_work[5:]
        i_work, album_id = i_work.split('_')

    i_work = str_toplus(i_work)

    # get target id
    check_group = rqst_method('groups.getById', {'group_ids': i_work})
    check_user = rqst_method('users.get', {'user_ids': i_work})

    # get target info (may glitch if id_group is the same as id_user)
    if check_group:
        t_work = str_tominus(check_group[0]['id'])
        t_info = check_group
        t_name = t_info[0]['name']
    elif check_user:
        t_work = str_toplus(check_user[0]['id'])
        t_info = check_user
        t_name = t_info[0]['first_name'] + ' ' + t_info[0]['last_name']
    else:
        logging.info('invalid url: ' + i_work)
        return

    logging.info(f'target info: {t_name} ({t_work})')

    # private page
    if t_info[0]['is_closed']:
        if 'is_member' in t_info[0] and t_info[0]['is_member']:
            pass
        elif 'can_access_closed' in t_info[0] and t_info[0]['can_access_closed']:
            pass
        else:
            logging.info(f'{t_name} closed')
            return

    # dump one album 2/2
    if album_id:
        get_album(t_info, t_work + '_' + album_id, '')
        return

    # steal albums 
    if sw_steal and '-' not in t_work:
        # from friends
        if options.steal_friends:
            friends = rqst_method('friends.get', {'user_id': t_work})
            for i, item in enumerate(friends['items'], start=1):
                parse_link(f'id{str(item)}', i, len(friends["items"]), False)

        # from groups    
        if options.steal_groups:
            groups = rqst_method('users.getSubscriptions', {'user_id': t_work})['groups']
            for i, item in enumerate(groups['items'], start=1):
                parse_link(f'club{str(item)}', i, len(groups["items"]), False)

    if '-' in t_work:
        directory = f'{str_cut(str_fix(check_group[0]["name"]), 100)} (-{check_group[0]["id"]})'
    else:
        directory = f'{str_cut(str_fix(check_user[0]["first_name"] + " " + check_user[0]["last_name"]), 100)} ({check_user[0]["id"]})'

    albums = rqst_method('photos.getAlbums', {'owner_id': t_work, 'album_ids': 0, 'need_system': 1})
    t_name_prefix = (f'[{num_seq} / {num_all} | ' if num_all > 2 else '[') + f'{str_cut(t_name)}]'

    # no access to albums
    if albums == False:
        logging.error(f'no access to albums')
        return

    os.makedirs(directory, exist_ok=True)
    os.chdir(directory)

    if albums == None: # public detected
        logging.warning('group photos disabled, downloading only wall photos')
        get_album(t_info, f'{t_work}_0', f'{t_name_prefix} 1 / 2 (profile) | ')
        get_album(t_info, f'{t_work}_00', f'{t_name_prefix} 2 / 2 (wall) | ')
    else:
        if '-' in t_work:
            get_album(t_info, f'{t_work}_00', f'{t_name_prefix} 0 / {len(albums["items"])} (wall) | ')

        for i, item in enumerate(albums["items"], start=1):
            if item['id'] == -6:
                get_album(t_info, f'{t_work}_0', f'{t_name_prefix} {i} / {albums["count"]} (profile) | ')

            elif item['id'] == -7:
                get_album(t_info, f'{t_work}_00', f'{t_name_prefix} {i} / {albums["count"]} (wall) | ')

            elif item['id'] == -15:
                get_album(t_info, f'{t_work}_000', f'{t_name_prefix} {i} / {albums["count"]} (saved) | ')

            elif item['id'] == -9000:
                get_album(t_info, f'{t_work}_-9000', f'{t_name_prefix} {i} / {albums["count"]} (tagged) | ')

            elif item['id'] == abs(item['id']):
                get_album(t_info, f'{t_work}_{str(item["id"])}', f'{t_name_prefix} {i} / {albums["count"]} ')

            else:
                logging.error(f'unexpected id: {item["id"]}') 
                
    os.chdir('..')

if __name__ == '__main__':
    parser = optparse.OptionParser()
    parser.add_option('-l', '--login', dest='login_info', default=login_info, help='Login info (token of login:pass)')
    parser.add_option('-t', '--threads', dest='threads_count', type=int, default='4', help='Number of threads')
    parser.add_option('-r', '--rewrite',  dest='rewrite_files', action='store_true', help='Force rewriting pictures')
    parser.add_option('-f', '--steal-friends', dest='steal_friends', action='store_true', help='Steal pics from friends')
    parser.add_option('-g', '--steal-groups', dest='steal_groups', action='store_true', help='Steal pics from friends')
    parser.add_option('-s', '--simulate', dest='simulate', action='store_true', help='Simulate (not download, only json with urls)')
    options, arguments = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    if not options.login_info:
        logging.info('login info is empty')
        sys.exit()
    elif len(options.login_info) == 85:
        vk = VkApi(token=options.login_info, api_version='5.121')
    elif ':' in options.login_info:
        lp = options.login_info.split(':')
        vk = VkApi(lp[0], lp[1], app_id=2685278, config_filename='phconfig.json')
        while True:
            try:
                vk.auth()
                os.remove('phconfig.json')
                rqst_method('users.get')[0]['id'] # auth test
                break
            except AuthError as ex:
                # idk
                if 'vk_api@python273.pw' in str(ex):
                    logging.error('unknown catched, retrying...')
                    time.sleep(10)
                else:
                    logging.error('autechre error: ' + str(ex))
                    sys.exit()

    #from vk_api.utils import enable_debug_mode
    #enable_debug_mode(vk, print_content=True)

    if not arguments:
        arguments.append(f'id{rqst_method("users.get")[0]["id"]}')

    for i, arg in enumerate(arguments, start=1):
        if os.path.exists(arg):
            get_json(arg)
        else:
            parse_link(arg, i, len(arguments))
