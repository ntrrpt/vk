mainfile = (
    "<!DOCTYPE html>\n"
    "<html>\n"
    "\n"
    "<head>\n"
    '    <meta charset="utf-8" />\n'
    "    <title>%s</title>\n"
    '    <meta content="width=device-width, initial-scale=1.0" name="viewport" />\n'
    '    <link href="style.css" rel="stylesheet" />\n'
    '    <script src="script.js" type="text/javascript"></script>\n'
    "</head>\n"
    "\n"
    '<body onload="CheckLocation();">\n'
    '    <div class="page_wrap">\n'
    '        <div class="page_header">\n'
    '            <div class="content">\n'
    '                <div class="text bold" title="%s">%s\n'
    '                    <div class="pull_right userpic_wrap">\n'
    '                        <div class="userpic" style="width: 25px; height: 25px">\n'
    '                            <a class="userpic_link" href="userpics/main.jpg">\n'
    '                                <img class="userpic" src="userpics/main.jpg" style="width: 25px; height: 25px" />\n'
    "                            </a>\n"
    "                        </div>\n"
    "                    </div>\n"
    "                </div>\n"
    "            </div>\n"
    "        </div>\n"
    '        <div class="page_body chat_page">\n'
    '            <div class="history">\n'
)

def_blank = (
    '<div class="message default clearfix" id="message%s">\n'
    '    <div class="pull_left userpic_wrap">\n'
    '        <div class="userpic" style="width: 42px; height: 42px">\n'
    '            <a class="userpic_link" href="userpics/id%s.jpg">\n'
    '                <img class="userpic" src="userpics/id%s.jpg" style="width: 42px; height: 42px" />\n'
    "            </a>\n"
    "        </div>\n"
    "    </div>\n"
    '    <div class="body">\n'
    '        <div class="pull_right date details">%s</div>\n'
    '        <div class="from_name">%s</div>\n'
    "%s"  # reply_message, fwd_messages
    '        <div class="text">\n%s\n</div>\n'
    "%s"  # fwd_text_prefix, pre_attachments
    "    </div>\n"
    "</div>\n"
    "%s\n"  # post_attachments
)

fwd_blank = (
    '<div class="pull_left forwarded userpic_wrap">\n'
    '    <!-- start-fwd-id=%s" -->\n'
    '    <div class="userpic" style="width: 42px; height: 42px">\n'
    '        <a class="userpic_link" href="userpics/id%s.jpg">\n'
    '            <img class="userpic" src="userpics/id%s.jpg" style="width: 42px; height: 42px" /></a>\n'
    "    </div>\n"
    "</div>\n"
    '<div class="forwarded body">\n'
    '    <div class="from_name">\n'
    '        %s<span class="details"> %s</span>\n'
    "    </div>\n"
    "%s"  # reply_message, fwd_messages
    '    <div class="text">\n%s</div>\n'
    "%s"  # fwd_text_prefix, pre_attachments
    "</div>\n"
    "%s"  # post_attachments
    "<!-- end-fwd -->\n"
)

jnd_blank = (
    '<div class="message default clearfix joined" id="%s">\n'
    '    <!-- joined-id%s-id%s" -->\n'
    '    <div class="body">\n'
    '        <div class="pull_right date details">%s</div>\n'
    '    <!-- joined-name %s" -->\n'
    "%s"  # reply_message, fwd_messages
    '        <div class="text">\n%s</div>\n'
    "%s"  # fwd_text_prefix, pre_attachments
    "    </div>\n"
    "</div>\n"
    "%s\n"  # post_attachments
)
