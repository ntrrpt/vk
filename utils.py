from bs4 import BeautifulSoup
from vk_api import VkApi

from time import sleep
import pathlib
import requests
import re

def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0
    return "%3.1f %s" % (num, 'TB')

def html_fmt(path):
    html = open(path, encoding='utf-8').read()
    soup = BeautifulSoup(html, "html.parser")
    fmt_html = soup.prettify()

    with open(path, "w", encoding='utf-8') as f:
        f.write(fmt_html)

def fix_val(number, digits):
    return f'{number:.{digits}f}'

def str_toplus(string):
    s = str(string)
    r = s[1:] if s.startswith('-') else s
    return r

def str_tominus(string):
    s = str(string)
    r = '-' + s if not s.startswith('-') else s
    return r

def str_cut(string, letters, postfix='...'):
    return string[:letters] + (string[letters:] and postfix)

def str_fix(string, letters = 100):
    r = re.sub(r'[/\\?%*:{}【】|"<>]', '', string) # [/\\?%*:{}【】|"<>]
    if letters:
        r = str_cut(r, letters)
    return r

def text_append(path, data):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(data + '\n')

def delete_file(filename):
    rem_file = pathlib.Path(filename)
    rem_file.unlink(missing_ok=True)

def expand_ranges(s):
    # "1-5,8,10-12" => 1,2,3,4,5,8,10,11,12
    def replace_range(match):
        start, end = map(int, match.group().split('-'))
        return ','.join(map(str, range(start, end + 1)))

    return re.sub(r'\d+-\d+', replace_range, s)

def rqst_str(url, retries = 5, headers={"Accept-Encoding": "identity"}):
    while retries:
        try: 
            with requests.get(url, headers) as request:
                if request:
                    return request.content
                return False
        except:
            sleep(5)
            retries -= 1

def check_ffmpeg():
    import subprocess as sp
    try:
        r = sp.run(['ffmpeg', '-version'], stdout=sp.PIPE, stderr=sp.PIPE)
        return r.returncode == 0
    except FileNotFoundError:
        return False

        