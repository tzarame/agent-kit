"""quoted.py - the KEY=VALUE words of a line of bash, as printf %q writes them: the lines of export of
install/gh-app.sh env, and the old kit's project files. They are read here, never run. Standard library only."""
import re

from kit import config

ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "e": "\x1b", "E": "\x1b",
        "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi(text, i):
    """the value of $'...' from text[i], just after the opening quote: (the value, the index after the quote)"""
    out = []
    while i < len(text):
        c = text[i]
        if c == "'":
            return "".join(out), i + 1
        if c != "\\" or i + 1 >= len(text):
            out.append(c)
            i += 1
            continue
        c = text[i + 1]
        if c in ANSI:
            out.append(ANSI[c])
            i += 2
        elif c == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", text[i + 2:])
            if not m:
                out.append("\\x")
                i += 2
                continue
            out.append(chr(int(m.group(), 16)))
            i += 2 + len(m.group())
        elif c in "01234567":
            m = re.match(r"[0-7]{1,3}", text[i + 1:])
            out.append(chr(int(m.group(), 8) & 0xFF))
            i += 1 + len(m.group())
        else:
            out.append("\\" + c)
            i += 2
    raise ValueError("a $'...' value is not closed")


def parse_q(text):
    """the KEY=VALUE words of a line of bash, as printf %q writes them, in a dict; ValueError on anything else"""
    words, cur, has, i = [], [], False, 0
    while i < len(text):
        c = text[i]
        if c in " \t\n":
            if has:
                words.append("".join(cur))
            cur, has, i = [], False, i + 1
        elif c == "\\":
            if i + 1 < len(text) and text[i + 1] != "\n":
                cur.append(text[i + 1])
            has, i = True, i + 2
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError("a '...' value is not closed")
            cur.append(text[i + 1:j])
            has, i = True, j + 1
        elif c == "$" and text[i + 1:i + 2] == "'":
            v, i = _ansi(text, i + 2)
            cur.append(v)
            has = True
        elif c == '"':
            j, part = i + 1, []
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and text[j + 1:j + 2] in ('"', "\\", "$", "`"):
                    part.append(text[j + 1])
                    j += 2
                elif text[j] in "$`":
                    raise ValueError("a \"...\" value with $ or `")
                else:
                    part.append(text[j])
                    j += 1
            if j >= len(text):
                raise ValueError('a "..." value is not closed')
            cur.append("".join(part))
            has, i = True, j + 1
        elif c in "$`;&|<>()*?[]{}":   # ~ and # inside a word are plain; %q escapes them at its start
            raise ValueError("%r is not a character of printf %%q" % c)
        else:
            cur.append(c)
            has, i = True, i + 1
    if has:
        words.append("".join(cur))
    out = {}
    for w in words:
        k, eq, v = w.partition("=")
        if not eq or not config.ENV_NAME.fullmatch(k):
            raise ValueError("%r is not KEY=VALUE" % w)
        out[k] = v
    return out
