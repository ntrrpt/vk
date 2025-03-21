from bs4 import BeautifulSoup
import re

def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0
    return "%3.1f %s" % (num, 'TB')

def html_fmt(path):
    html = open(path).read()
    soup = BeautifulSoup(html, "html.parser")
    fmt_html = soup.prettify()

    with open(path, "w") as f:
        f.write(fmt_html)

def fix_val(number, digits):
    return f'{number:.{digits}f}'

def str_toplus(string):
    s = str(string)
    r = s[1:] if s.startswith('-') else s
    return r

def str_tominus(string):
    s = str(s)
    r = '-' + s if not s.startswith('-') else s
    return r

def str_cut(string, letters, postfix='...'):
    return string[:letters] + (string[letters:] and postfix)

def str_fix(string, letters = 100):
    sub = re.sub(r'[/\\?%*\-\[\]{}:|"<>]', '', string)
    return str_cut(sub, letters)

def text_append(path, data):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(data + '\n')