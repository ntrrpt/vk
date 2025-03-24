from bs4 import BeautifulSoup
from vk_api import VkApi
import pathlib
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
