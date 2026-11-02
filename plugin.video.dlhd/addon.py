# -*- coding: utf-8 -*-
import re
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, quote_plus, parse_qs

import requests
import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin
import xbmcaddon

addon_url = sys.argv[0]
addon_handle = int(sys.argv[1])
params = dict(parse_qsl(sys.argv[2][1:]))
addon = xbmcaddon.Addon(id='plugin.video.dlhd')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
ICON = addon.getAddonInfo('icon')
FANART = addon.getAddonInfo('fanart')
BASE_SEED = 'https://dlive.sx/'


def log(msg):
    try:
        log_dir = xbmcvfs.translatePath('special://logpath/')
        path = os.path.join(log_dir, 'dlhd.log')
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(msg, str):
            text = f'[{stamp}]: {msg}\n'
        else:
            text = f'[{stamp}]: {repr(msg)}\n'
        with open(path, 'a', encoding='utf-8') as f:
            f.write(text)
    except Exception:
        pass


def normalize_origin(url):
    try:
        p = urlparse(url)
        return f'{p.scheme}://{p.netloc}/'
    except Exception:
        return BASE_SEED


def resolve_base(seed):
    try:
        res = requests.get(seed, headers={'User-Agent': UA}, timeout=10, allow_redirects=True)
        return normalize_origin(res.url or seed)
    except Exception as e:
        log(f'resolve_base fail: {e}')
        return normalize_origin(seed)


def get_active_base():
    base = addon.getSetting('active_baseurl')
    if not base:
        base = resolve_base(BASE_SEED)
        addon.setSetting('active_baseurl', base)
    if not base.endswith('/'):
        base += '/'
    return base


def set_active_base(new_base):
    if not new_base.endswith('/'):
        new_base += '/'
    addon.setSetting('active_baseurl', new_base)


def abs_url(path):
    return urljoin(get_active_base(), path.lstrip('/'))


def build_url(query):
    return addon_url + '?' + urlencode(query)


def getKodiversion():
    try:
        return int(xbmc.getInfoLabel('System.BuildVersion')[:2])
    except Exception:
        return 18


def addDir(title, url, isFolder=True):
    li = xbmcgui.ListItem(label=title)
    info = {'title': title, 'plot': title, 'mediatype': 'video'}
    kv = getKodiversion()
    if kv < 20:
        li.setInfo('video', info)
    else:
        tag = li.getVideoInfoTag()
        tag.setMediaType('video')
        tag.setTitle(title)
        tag.setPlot(title)
    li.setArt({'icon': ICON, 'fanart': FANART})
    li.setProperty('IsPlayable', 'false' if isFolder else 'true')
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=url, listitem=li, isFolder=isFolder)


def closeDir():
    xbmcplugin.endOfDirectory(addon_handle)


def Main_Menu():
    menu = [
        ['[B][COLOR red]LIVE SPORTS SCHEDULE[/COLOR][/B]', 'sched'],
        ['[B][COLOR red]LIVE TV CHANNELS[/COLOR][/B]', 'live_tv'],
        ['[B][COLOR red]SEARCH EVENTS SCHEDULE[/COLOR][/B]', 'search'],
        ['[B][COLOR red]SEARCH LIVE TV CHANNELS[/COLOR][/B]', 'search_channels'],
        ['[B][COLOR red]REFRESH CATEGORIES[/COLOR][/B]', 'refresh_sched'],
        ['[B][COLOR red]SET ACTIVE DOMAIN (AUTO)[/COLOR][/B]', 'resolve_base_now'],
    ]
    for title, typ in menu:
        addDir(title, build_url({'mode': 'menu', 'serv_type': typ}))
    closeDir()


def Menu_Trans():
    cats = getCategTrans()
    for name, _ in cats:
        addDir(name, build_url({'mode': 'showChannels', 'trType': name}))
    closeDir()


def getCategTrans():
    try:
        html_text = requests.get(abs_url('index.php'), headers={'User-Agent': UA, 'Referer': get_active_base()}, timeout=10).text
        block = re.search(r'<div[^>]+class="filters"[^>]*>(.*?)</div>', html_text, re.I | re.S)
        if not block:
            return []
        anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block.group(1), re.I | re.S)
        out = []
        seen = set()
        for href, text in anchors:
            name = re.sub(r'<[^>]+>', '', text)
            name = re.sub(r'\s+', ' ', name).strip()
            if not name or name.lower() == 'all':
                continue
            if name not in seen:
                seen.add(name)
                out.append((name, href))
        return out
    except Exception as e:
        log(f'getCategTrans fail: {e}')
        return []


def getTransData(categ):
    try:
        url = abs_url('index.php?cat=' + quote_plus(categ))
        text = requests.get(url, headers={'User-Agent': UA, 'Referer': get_active_base()}, timeout=10).text
        events = re.findall(
            r'<div\s+class="schedule__event">.*?'
            r'<div\s+class="schedule__eventHeader"[^>]*?>\s*(?:<[^>]+>)*?'
            r'<span\s+class="schedule__time"[^>]*data-time="([^"]+)"[^>]*>.*?</span>\s*'
            r'<span\s+class="schedule__eventTitle">\s*([^<]+)\s*</span>.*?'
            r'</div>\s*<div\s+class="schedule__channels">(.*?)</div>',
            text, re.I | re.S
        )
        out = []
        for time_str, title, block in events:
            channels = []
            for href, title_attr, link_text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>', block, re.I | re.S):
                qs = dict(parse_qsl(urlparse(href).query))
                cid = qs.get('id')
                if not cid:
                    continue
                display = re.sub(r'<[^>]+>', '', title_attr or link_text).strip() or 'Channel'
                channels.append({'channel_name': display, 'channel_id': cid})
            if channels:
                out.append({'title': f'{time_str} {title}', 'channels': channels})
        return out
    except Exception as e:
        log(f'getTransData fail: {e}')
        return []


def ShowChannels(categ, channels):
    for item in channels:
        addDir(item['title'], build_url({'mode': 'trList', 'trType': categ, 'channels': json.dumps(item['channels'])}))
    closeDir()


def TransList(categ, channels):
    for item in channels:
        ch_title = item.get('channel_name')
        ch_id = item.get('channel_id')
        if not ch_id:
            continue
        addDir(ch_title, build_url({'mode': 'trLinks', 'trData': json.dumps({'channels': [{'channel_name': ch_title, 'channel_id': ch_id}]})}), False)
    closeDir()


def channels():
    try:
        text = requests.post(abs_url('24-7-channels.php'), headers={'User-Agent': UA, 'Referer': get_active_base()}, timeout=10).text
        items = []
        for href, title, body in re.findall(r'<a\s+class="card"[^>]*href="([^"]+)"[^>]*data-title="([^"]*)"[^>]*>(.*?)</a>', text, re.I | re.S):
            name = re.sub(r'<[^>]+>', '', title).strip() or re.sub(r'<[^>]+>', '', body).strip()
            if name:
                items.append([href, name])
        return items
    except Exception as e:
        log(f'channels fail: {e}')
        return []


def list_gen():
    for href, name in channels():
        addDir(name, build_url({'mode': 'play', 'url': abs_url(href)}), False)
    closeDir()


def _origin(url):
    try:
        p = urlparse(url)
        return f'{p.scheme}://{p.netloc}'
    except Exception:
        return ''


def _candidate_stream_urls(cid):
    cid = str(cid or '').strip()
    if not cid:
        return []

    path_variants = [
        f'stream/stream-{cid}.php',
        f'watch/stream-{cid}.php',
        f'hub/stream-{cid}.php',
        f'plus/stream-{cid}.php',
        f'casting/stream-{cid}.php',
        f'player/stream-{cid}.php',
        f'cast/stream-{cid}.php',
        f'watch.php?id={quote_plus(cid)}',
        f'watchs2watch.php?id={quote_plus(cid)}',
    ]

    urls = []
    seen = set()
    for p in path_variants:
        full_url = abs_url(p)
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)
    return urls


def _fetch(session, url, referer=None, timeout=15):
    if not url:
        raise RuntimeError('Empty URL')
    if url.startswith('//'):
        url = 'https:' + url
    headers = {'User-Agent': UA, 'Referer': referer or get_active_base()}
    log(f'[PlayStream] GET {url} (ref={headers["Referer"]})')
    r = session.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text, r.url


def _find_iframe(page):
    m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', page, re.I | re.S)
    if m:
        return m.group(1).strip()
    return None


def _extract_m3u8(page):
    patterns = [
        r'"(https?://[^"\']+\.m3u8(?:\?[^"\']+)?)"',
        r"'(https?://[^\"\']+\.m3u8(?:\?[^\"\']+)?)'",
        r'(https?://[^\s"\'>]+\.m3u8(?:\?[^
\s"\'>]+)?)',
    ]
    for pat in patterns:
        m = re.search(pat, page or '', re.I | re.S)
        if m:
            return m.group(1).strip()
    return None


def PlayStream(link):
    try:
        session = requests.Session()
        base = get_active_base()
        formatted = link
        if 'watch.php?id=' in formatted:
            parsed = urlparse(formatted)
            q = dict(parse_qsl(parsed.query))
            cid = q.get('id')
            if cid:
                formatted = f'https://thedaddy.pk/stream/stream-{cid}.php'
                log(f'[PlayStream] normalized input watch.php -> {formatted}')

        html1, _ = _fetch(session, formatted, referer=base)
        source_url = _find_iframe(html1) or formatted
        if not source_url:
            raise RuntimeError(f'No source iframe found for {formatted}')

        log(f'source_url: {source_url}')
        page2, _ = _fetch(session, source_url, referer=base)

        m3u8_playlist_url = _extract_m3u8(page2)
        if not m3u8_playlist_url:
            m3u8_playlist_url = _extract_m3u8(html1)
        if not m3u8_playlist_url:
            raise RuntimeError(f'No HLS playlist found in page after {source_url}')

        host = _origin(source_url) or _origin(formatted) or base
        if not host.endswith('/'):
            host += '/'
        header_dict = {
            'User-Agent': UA,
            'Referer': host,
            'Origin': host.rstrip('/')
        }
        header_str = '&'.join(f'{k}={quote_plus(v)}' for k, v in header_dict.items())
        final_hls = f'{m3u8_playlist_url}|{header_str}'
        log(f'[PlayStream] Final HLS = {final_hls}')

        liz = xbmcgui.ListItem(path=final_hls)
        liz.setProperty('inputstream', 'inputstream.adaptive')
        liz.setProperty('inputstream.adaptive.manifest_type', 'hls')
        liz.setMimeType('application/vnd.apple.mpegurl')
        liz.setContentLookup(False)
        xbmcplugin.setResolvedUrl(addon_handle, True, liz)

    except Exception as e:
        log(f'[PlayStream] Exception: {e}\n{traceback.format_exc()}')
        try:
            xbmcgui.Dialog().ok('DLHD', f'Playback failed\n{e}')
        except Exception:
            pass


def Search_Events():
    try:
        term = xbmcgui.Dialog().input('Enter search term')
        if not term:
            return
        text = requests.get(abs_url('index.php'), headers={'User-Agent': UA, 'Referer': get_active_base()}, timeout=10).text
        rows = {}
        seen = set()
        for time_str, title, block in re.findall(
            r'<div\s+class="schedule__event">.*?'
            r'<div\s+class="schedule__eventHeader"[^>]*?>\s*(?:<[^>]+>)*?'
            r'<span\s+class="schedule__time"[^>]*data-time="([^"]+)"[^>]*>.*?</span>\s*'
            r'<span\s+class="schedule__eventTitle">\s*([^<]+)\s*</span>.*?'
            r'</div>\s*<div\s+class="schedule__channels">(.*?)</div>',
            text, re.I | re.S
        ):
            if term.lower() not in title.lower():
                continue
            channels = []
            for href, title_attr, link_text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>', block, re.I | re.S):
                qs = dict(parse_qsl(urlparse(href).query))
                cid = qs.get('id')
                if not cid:
                    continue
                display = re.sub(r'<[^>]+>', '', title_attr or link_text).strip() or 'Channel'
                key = (title, cid)
                if key not in seen:
                    seen.add(key)
                    channels.append({'channel_name': display, 'channel_id': cid})
            if channels:
                rows.setdefault(f'{time_str} {title}', []).extend(channels)
        for title, items in rows.items():
            addDir(title, build_url({'mode': 'trList', 'trType': 'search', 'channels': json.dumps(items)}))
        closeDir()
    except Exception as e:
        log(f'Search_Events fail: {e}')
        xbmcgui.Dialog().ok('DLHD', 'Search failed.')


def Search_Channels():
    try:
        term = xbmcgui.Dialog().input('Enter channel name')
        if not term:
            return
        text = requests.get(abs_url('index.php'), headers={'User-Agent': UA, 'Referer': get_active_base()}, timeout=10).text
        items = []
        seen = set()
        for href, title_attr, link_text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>', text, re.I | re.S):
            display = re.sub(r'<[^>]+>', '', title_attr or link_text).strip()
            if term.lower() not in display.lower():
                continue
            qs = dict(parse_qsl(urlparse(href).query))
            cid = qs.get('id')
            if not cid:
                continue
            key = (display, cid)
            if key not in seen:
                seen.add(key)
                items.append({'channel_name': display, 'channel_id': cid})
        for item in items:
            addDir(item['channel_name'], build_url({'mode': 'trLinks', 'trData': json.dumps({'channels': [item]})}), False)
        closeDir()
    except Exception as e:
        log(f'Search_Channels fail: {e}')
        xbmcgui.Dialog().ok('DLHD', 'Search failed.')


def refresh_active_base():
    base = resolve_base(BASE_SEED)
    set_active_base(base)
    xbmcgui.Dialog().ok('DLHD', f'Active domain set to:\n{base}')
    xbmc.executebuiltin('Container.Refresh')


def getSource(trData):
    try:
        payload = json.loads(trData)
        channels = payload.get('channels', [])
        if not channels:
            return
        cid = channels[0].get('channel_id')
        if not cid:
            return
        for stream_url in _candidate_stream_urls(cid):
            try:
                PlayStream(stream_url)
                return
            except Exception as e:
                log(f'getSource candidate failed {stream_url}: {e}')
    except Exception as e:
        log(f'getSource fail: {e}')


mode = params.get('mode')
if not mode:
    Main_Menu()
else:
    if mode == 'menu':
        serv_type = params.get('serv_type')
        if serv_type == 'sched':
            Menu_Trans()
        elif serv_type == 'live_tv':
            list_gen()
        elif serv_type == 'search':
            Search_Events()
        elif serv_type == 'search_channels':
            Search_Channels()
        elif serv_type == 'refresh_sched':
            xbmc.executebuiltin('Container.Refresh')
        elif serv_type == 'resolve_base_now':
            refresh_active_base()
    elif mode == 'showChannels':
        ShowChannels(params.get('trType'), getTransData(params.get('trType')))
    elif mode == 'trList':
        TransList(params.get('trType'), json.loads(params.get('channels')))
    elif mode == 'trLinks':
        getSource(params.get('trData'))
    elif mode == 'play':
        PlayStream(params.get('url'))
