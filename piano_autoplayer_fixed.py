import sys
import os
import time
import re
import ctypes
import threading
import json
import html
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from bs4 import BeautifulSoup

# =============================================================
# RESOURCE & SYSTEM HELPERS
# =============================================================

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

user32 = ctypes.windll.user32
VK_F8 = 0x77  # F8 Key Virtual Code

# =============================================================
# HARDWARE DIRECTINPUT KEYBOARD DRIVER
# =============================================================

PUL = ctypes.POINTER(ctypes.c_ulong)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class INPUT_I(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", INPUT_I)
    ]

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
VK_SHIFT = 0x10

PIANO_KEY_MAP = "1!2@34$5%6^78*9(0qQwWeErRtTyYuUiIoOpPaAsSdDfFgGhHjJkKlLzZxXcCvVbBnNmM"

CHAR_TO_VK = {
    '1': (0x31, False), '!': (0x31, True),
    '2': (0x32, False), '@': (0x32, True),
    '3': (0x33, False),
    '4': (0x34, False), '$': (0x34, True),
    '5': (0x35, False), '%': (0x35, True),
    '6': (0x36, False), '^': (0x36, True),
    '7': (0x37, False),
    '8': (0x38, False), '*': (0x38, True),
    '9': (0x39, False), '(': (0x39, True),
    '0': (0x30, False)
}

for char_code in range(ord('a'), ord('z') + 1):
    c_lower = chr(char_code)
    c_upper = c_lower.upper()
    vk = 0x41 + (char_code - ord('a'))
    CHAR_TO_VK[c_lower] = (vk, False)
    CHAR_TO_VK[c_upper] = (vk, True)


class DirectInputKeyboardDriver:
    @staticmethod
    def _send_scancode(vk_code, is_keyup):
        scan_code = user32.MapVirtualKeyW(vk_code, 0)
        flags = KEYEVENTF_SCANCODE
        if is_keyup:
            flags |= KEYEVENTF_KEYUP

        extra = ctypes.c_ulong(0)
        ii_ = INPUT_I()
        ii_.ki = KEYBDINPUT(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = INPUT(ctypes.c_ulong(INPUT_KEYBOARD), ii_)
        user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def press_char(self, char):
        if char not in CHAR_TO_VK:
            return
        vk_code, needs_shift = CHAR_TO_VK[char]

        if needs_shift:
            self._send_scancode(VK_SHIFT, False)
        
        self._send_scancode(vk_code, False)
        time.sleep(0.018)
        self._send_scancode(vk_code, True)

        if needs_shift:
            self._send_scancode(VK_SHIFT, True)

    def press_chord(self, chars):
        has_shift = any(CHAR_TO_VK[c][1] for c in chars if c in CHAR_TO_VK)
        
        if has_shift:
            self._send_scancode(VK_SHIFT, False)

        pressed = []
        for c in chars:
            if c in CHAR_TO_VK:
                vk, _ = CHAR_TO_VK[c]
                self._send_scancode(vk, False)
                pressed.append(vk)

        time.sleep(0.025)

        for vk in pressed:
            self._send_scancode(vk, True)

        if has_shift:
            self._send_scancode(VK_SHIFT, True)


def focus_roblox_or_alt_tab():
    roblox_hwnd = None

    def enum_windows_callback(hwnd, extra):
        nonlocal roblox_hwnd
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                if "roblox" in buff.value.lower():
                    roblox_hwnd = hwnd
                    return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    if roblox_hwnd:
        user32.ShowWindow(roblox_hwnd, 9)
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(roblox_hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
        return True
    else:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x09, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(0x09, 0, 2, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        return False


def jaro_winkler_fast(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_dist = max(len1, len2) // 2 - 1
    if match_dist < 0:
        match_dist = 0

    matches1, matches2 = [False] * len1, [False] * len2
    num_matches = 0

    for i in range(len1):
        start = max(0, i - match_dist)
        end = min(len2, i + match_dist + 1)
        for j in range(start, end):
            if not matches2[j] and s1[i] == s2[j]:
                matches1[i] = True
                matches2[j] = True
                num_matches += 1
                break

    if num_matches == 0:
        return 0.0

    transpositions = 0
    k = 0
    for i in range(len1):
        if matches1[i]:
            while not matches2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    jaro = (num_matches / len1 + num_matches / len2 + (num_matches - transpositions / 2) / num_matches) / 3.0
    prefix = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + (prefix * 0.1 * (1.0 - jaro))


def sanitize_piano_sheet(text: str) -> str:
    """Removes VirtualPiano rating noise, boilerplate text, and website descriptions."""
    if not text:
        return ""
    
    junk_patterns = [
        r"Average rating.*",
        r"Vote count:.*",
        r"No votes so far!.*",
        r"If you have any specific feedback.*",
        r".*is a song by.*",
        r".*Use your computer keyboard to play.*",
        r".*This is an Easy song.*",
        r".*The recommended time to play.*",
        r".*is classified in the genres:.*",
        r".*You can also find other similar songs.*",
        r"Rate This Music Sheet",
        r"Submit Rating",
        r"Thank you for rating",
        r"rmp-.*",
        r"Comments"
    ]
    
    lines = text.splitlines()
    clean_lines = []
    
    for line in lines:
        sline = line.strip()
        if not sline:
            continue
            
        if any(re.search(pat, sline, re.IGNORECASE) for pat in junk_patterns):
            continue
            
        clean_lines.append(sline)
        
    return "\n".join(clean_lines)


GITHUB_INDEX_URLS = [
    "https://raw.githubusercontent.com/rblxautopiano-alt/autopiano/refs/heads/main/piano_sheets.txt",
    "https://raw.githubusercontent.com/rblxautopiano-alt/autopiano/refs/heads/main/piano_sheets%20(1).txt",
    "https://raw.githubusercontent.com/rblxautopiano-alt/autopiano/refs/heads/main/piano_sheets%20(2).txt",
    "https://raw.githubusercontent.com/rblxautopiano-alt/autopiano/refs/heads/main/piano_sheets%20(3).txt"
]


class SheetPipelineEngine:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        })
        self.catalog = []
        self.catalog_map = {}
        self.lock = threading.Lock()

    def _add_song(self, title, slug, source, sheet=None, custom_tags=""):
        slug_clean = slug.lower().strip()
        if not slug_clean or len(slug_clean) < 2:
            return

        clean_key = f"{re.sub(r'[\s\W]', '', title.lower())}_{source}"
        normalized_tags = re.sub(r"[/\_,\-]", " ", custom_tags).lower()
        condensed_tags = re.sub(r'[\s\W_]', '', normalized_tags)

        with self.lock:
            # FIX: If song already exists, MERGE custom tags so GitHub metadata is NEVER lost!
            if clean_key in self.catalog_map:
                existing = self.catalog_map[clean_key]
                if normalized_tags and normalized_tags not in existing["searchableText"]:
                    existing["searchableText"] += " " + normalized_tags
                    existing["condensedSearchable"] += condensed_tags
                if sheet and not existing.get("sheet"):
                    existing["sheet"] = sheet
            else:
                display_title = title if "[" in title else f"{title} [{source.title()}]"
                searchable = f"{display_title} {slug_clean} {normalized_tags}".lower()
                condensed = re.sub(r'[\s\W_]', '', searchable)

                item = {
                    "title": display_title,
                    "rawTitle": title,
                    "slug": slug_clean,
                    "source": source,
                    "sheet": sheet,
                    "cleanTitle": re.sub(r'[\s\W]', '', display_title.lower()),
                    "cleanSlug": slug_clean,
                    "searchableText": searchable,
                    "condensedSearchable": condensed
                }
                self.catalog.append(item)
                self.catalog_map[clean_key] = item

    def init_catalog_async(self, status_cb):
        status_cb("Fetching GitHub Indexes & Web Sitemaps...")

        def fetch_github(url):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if not line:
                            continue

                        tags_str = ""
                        if " - " in line:
                            parts = line.split(" - ")
                            title_src = parts[0].strip()
                            tags_str = " ".join(parts[1:]).strip()
                        else:
                            title_src = line

                        match = re.match(r"^(.*?)\s*\[([^\]]+)\]$", title_src.strip())
                        if match:
                            raw_title = match.group(1).strip()
                            src_bracket = match.group(2).strip().lower()
                        else:
                            raw_title = title_src.strip()
                            src_bracket = "vpsheet"

                        source = "virtualpiano" if "virtualpiano" in src_bracket else ("playpianosheets" if "playpianosheets" in src_bracket else "vpsheet")
                        slug = re.sub(r"[^\w\-_]", "", raw_title.lower().replace(" ", "-"))
                        
                        # Preserve full original line as searchable tags
                        full_tags = f"{tags_str} {line}".lower()
                        self._add_song(raw_title, slug, source, custom_tags=full_tags)
            except Exception as e:
                print(f"GitHub fetch error ({url}): {e}")

        def fetch_sitemap(url, source, pattern):
            try:
                resp = self.session.get(url, timeout=6)
                if resp.status_code == 200:
                    for slug in set(re.findall(pattern, resp.text)):
                        if slug.lower() not in ("all", "maker", "updates", "search", "category", "tag"):
                            self._add_song(slug.replace("-", " ").title(), slug, source)
            except Exception as e:
                print(f"Sitemap error ({url}): {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_github, url) for url in GITHUB_INDEX_URLS]
            for sm in ["sitemap-0.xml", "sitemap-1.xml", "sitemap-2.xml", "sitemap.xml"]:
                futures.append(executor.submit(fetch_sitemap, f"https://playpianosheets.com/{sm}", "playpianosheets", r"playpianosheets\.com/sheets/([\w\-_]+)"))
            futures.append(executor.submit(fetch_sitemap, "https://vpsheet.com/sitemap.xml", "vpsheet", r"vpsheet\.com/sheet/([\w\-_]+)"))
            for sm in ["music_sheet-sitemap.xml", "music_sheet-sitemap1.xml", "wp-sitemap-posts-music_sheet-1.xml"]:
                futures.append(executor.submit(fetch_sitemap, f"https://virtualpiano.net/{sm}", "virtualpiano", r"virtualpiano\.net/music-sheet/([\w\-_]+)"))

            for f in futures:
                f.result()

        # Deterministic sorting so list ordering NEVER changes randomly on app restart
        with self.lock:
            self.catalog.sort(key=lambda x: x["title"].lower())

        status_cb(f"Ready ({len(self.catalog)} songs indexed)")

    def search_fuzzy(self, query: str):
        if not query.strip():
            return self.catalog

        q_raw = query.lower().strip()
        q_clean = re.sub(r'[\s\W_]', '', q_raw)
        tokens = [w for w in re.findall(r'\w+', q_raw)]
        tokens_clean = [re.sub(r'[\s\W_]', '', tok) for tok in tokens if len(tok) > 0]

        scored = []
        for item in self.catalog:
            searchable = item["searchableText"]
            condensed = item["condensedSearchable"]

            score = 0.0

            # 1. Exact condensed string match (e.g. "fireforce" in "fireforceop1")
            if q_clean in condensed or q_clean in searchable:
                score = 1.0
            else:
                # 2. Token ratio match
                hits = 0
                for tok, ctok in zip(tokens, tokens_clean):
                    if tok in searchable or ctok in condensed:
                        hits += 1

                if tokens:
                    token_ratio = hits / len(tokens)
                    if token_ratio == 1.0:
                        score = 0.95
                    elif token_ratio > 0:
                        jaro = jaro_winkler_fast(q_clean, item["cleanTitle"])
                        score = (token_ratio * 0.60) + (jaro * 0.40)

            if score > 0.20:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]

    def extract_vpsheet_max_notes(self, html_text: str) -> str:
        if not html_text:
            return None
        candidates = []
        normalized = html_text.replace('\\"', '"').replace('\\\\n', '\n').replace('\\n', '\n')

        for m in re.finditer(r'"textSheet"\s*:\s*"([^"]+)"', normalized):
            clean = m.group(1).replace("\\t", "\t").replace("\\r", "").replace('\\"', '"')
            if len(clean) > 15:
                candidates.append(clean)

        for m in re.finditer(r'"text"\s*:\s*"([^"]+)"', html_text):
            clean = m.group(1).replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "").replace('\\"', '"')
            if len(clean) > 15:
                candidates.append(clean)

        soup = BeautifulSoup(html_text, 'html.parser')
        for pre in soup.find_all('pre'):
            clean = pre.get_text()
            if len(clean) > 15:
                candidates.append(clean)

        best_sheet, max_notes = None, 0
        note_pattern = re.compile(r"[\w\[\]\!\@\$\%\^\*\(\)]")

        for cand in candidates:
            note_count = len(note_pattern.findall(cand))
            if note_count > max_notes:
                max_notes = note_count
                best_sheet = cand

        return best_sheet

    def fetch_sheet_content(self, song: dict) -> str:
        if song.get("sheet") and len(song["sheet"]) > 10:
            return sanitize_piano_sheet(song["sheet"])

        source, slug = song["source"], song["slug"]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        try:
            # SOURCE 1: PlayPianoSheets
            if source == "playpianosheets":
                resp = self.session.get(f"https://playpianosheets.com/sheets/{slug}", headers=headers, timeout=8)
                if resp.status_code == 200:
                    html_text = resp.text
                    
                    try:
                        soup = BeautifulSoup(html_text, 'html.parser')
                        script = soup.find('script', id='__NEXT_DATA__')
                        if script and script.string:
                            data = json.loads(script.string)
                            page_props = data.get('props', {}).get('pageProps', {})
                            sheet_obj = page_props.get('sheet', {}) or page_props.get('data', {})
                            content = sheet_obj.get('content') or sheet_obj.get('sheet') or sheet_obj.get('textSheet')
                            if content and len(str(content)) > 10:
                                return sanitize_piano_sheet(html.unescape(str(content)))
                    except Exception:
                        pass

                    match = re.search(r'"content"\s*:\s*"([^"]+)"', html_text)
                    if match:
                        try:
                            decoded = match.group(1).encode().decode('unicode_escape')
                            if len(decoded) > 10:
                                return sanitize_piano_sheet(html.unescape(decoded))
                        except Exception:
                            pass

                    tokens = re.findall(r'<span id="token-\d+"[^>]*>(.*?)</span>', html_text)
                    if tokens:
                        clean_toks = [re.sub(r'<[^>]+>', '', t).strip() for t in tokens if t.strip()]
                        if clean_toks:
                            return sanitize_piano_sheet(html.unescape(" ".join(clean_toks)))

            # SOURCE 2: VPSheet
            elif source == "vpsheet":
                resp = self.session.get(f"https://vpsheet.com/sheet/{slug}", headers=headers, timeout=8)
                if resp.status_code == 200:
                    html_text = resp.text

                    try:
                        soup = BeautifulSoup(html_text, 'html.parser')
                        script = soup.find('script', id='__NEXT_DATA__')
                        if script and script.string:
                            data = json.loads(script.string)
                            page_props = data.get('props', {}).get('pageProps', {})
                            sheet_obj = page_props.get('sheet', {}) or page_props
                            text_sheet = sheet_obj.get('textSheet') or sheet_obj.get('content') or sheet_obj.get('sheet')
                            if text_sheet and len(str(text_sheet)) > 10:
                                return sanitize_piano_sheet(html.unescape(str(text_sheet)))
                    except Exception:
                        pass

                    extracted = self.extract_vpsheet_max_notes(html_text)
                    if extracted and len(extracted) > 10:
                        return sanitize_piano_sheet(html.unescape(extracted))

            # SOURCE 3: VirtualPiano
            elif source == "virtualpiano":
                resp = self.session.get(f"https://virtualpiano.net/music-sheet/{slug}/", headers=headers, timeout=8)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    paras = []
                    for p in soup.find_all(['p', 'pre']):
                        txt = p.get_text()
                        if not any(fs in txt for fs in ["Rate This Music Sheet", "Submit Rating", "Thank you for rating", "rmp-", "Comments"]):
                            cleaned = re.sub(r'\s+', ' ', txt).strip()
                            if len(cleaned) > 2:
                                paras.append(cleaned)
                    if paras:
                        raw_combined = "\n".join(paras)
                        return sanitize_piano_sheet(html.unescape(raw_combined))

        except Exception as e:
            print(f"Sheet fetch error ({song['title']}): {e}")

        return None


# =============================================================
# MONOCHROME FLASHY GUI INTERFACE (F8 KILLSWITCH)
# =============================================================

class PianoAutoplayerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Roblox Piano Autoplayer")
        self.root.geometry("520x680")
        self.root.configure(bg="#0A0A0C")

        ico_file = resource_path("my_icon.ico")
        if os.path.exists(ico_file):
            try:
                self.root.iconbitmap(ico_file)
            except Exception:
                pass

        self.root.attributes("-topmost", True)

        self.driver = DirectInputKeyboardDriver()
        self.pipeline = SheetPipelineEngine()

        self.is_playing = False
        self.is_paused = False
        self.tempo = 0.15
        self.pitch_shift = 0
        self.current_results = []

        self._apply_theme()
        self._build_ui()
        
        threading.Thread(target=self._f8_killswitch_listener, daemon=True).start()
        threading.Thread(target=self._init_data_async, daemon=True).start()

    def _apply_theme(self):
        style = ttk.Style()
        style.theme_use('clam')

        BG_DARK = "#0A0A0C"
        CARD_BG = "#121216"
        ACCENT_WHITE = "#FFFFFF"
        BORDER_GRAY = "#22222A"

        style.configure("TFrame", background=BG_DARK)
        style.configure("Card.TFrame", background=CARD_BG, relief="solid", borderwidth=1)
        
        style.configure("TLabel", background=BG_DARK, foreground="#E1E1E6", font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=CARD_BG, foreground="#E1E1E6", font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=BG_DARK, foreground=ACCENT_WHITE, font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", background=BG_DARK, foreground="#A0A0B0", font=("Consolas", 8, "italic"))

        style.configure("TCheckbutton", background=BG_DARK, foreground="#CCCCCC", font=("Segoe UI", 8))
        style.map("TCheckbutton", background=[("active", BG_DARK)], foreground=[("active", ACCENT_WHITE)])

        style.configure("TButton", 
                        background="#181820", 
                        foreground="#FFFFFF", 
                        borderwidth=1, 
                        bordercolor=BORDER_GRAY, 
                        font=("Segoe UI", 9, "bold"),
                        padding=4)
        
        style.map("TButton",
                  background=[("active", "#FFFFFF"), ("disabled", "#101014")],
                  foreground=[("active", "#000000"), ("disabled", "#444450")])

        style.configure("Action.TButton", 
                        background="#FFFFFF", 
                        foreground="#000000", 
                        font=("Segoe UI", 10, "bold"),
                        padding=6)
        
        style.map("Action.TButton",
                  background=[("active", "#D0D0D0")],
                  foreground=[("active", "#000000")])

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        top_bar = ttk.Frame(main)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        self.topmost_var = tk.BooleanVar(value=True)
        topmost_chk = ttk.Checkbutton(top_bar, text="📌 Always On Top", variable=self.topmost_var, command=self._toggle_topmost)
        topmost_chk.pack(side=tk.LEFT)

        ttk.Label(top_bar, text="⚡ F8: EMERGENCY STOP", foreground="#FF3B30", font=("Consolas", 9, "bold")).pack(side=tk.RIGHT)

        ttk.Label(main, text="SEARCH MUSIC / TAGS", style="Header.TLabel").pack(anchor=tk.W, pady=(4, 2))
        
        search_frame = ttk.Frame(main)
        search_frame.pack(fill=tk.X, pady=(0, 6))

        self.search_var = tk.StringVar()
        self.search_var.trace('w', self._on_search)
        
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, bg="#14141A", fg="#FFFFFF", 
                                insertbackground="#FFFFFF", relief="solid", bd=1, font=("Segoe UI", 10))
        search_entry.pack(fill=tk.X, ipady=4)

        list_container = ttk.Frame(main)
        list_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        scrollbar = tk.Scrollbar(list_container, bg="#101014", troughcolor="#0A0A0C", activebackground="#FFFFFF", bd=0)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(list_container, bg="#121218", fg="#E0E0E0", selectbackground="#FFFFFF", selectforeground="#000000",
                                  bd=1, relief="solid", highlightthickness=0, font=("Consolas", 9),
                                  yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind('<<ListboxSelect>>', self._on_select_song)

        ctrl_card = ttk.Frame(main, style="Card.TFrame", padding=8)
        ctrl_card.pack(fill=tk.X, pady=(0, 8))

        c_row1 = ttk.Frame(ctrl_card, style="Card.TFrame")
        c_row1.pack(fill=tk.X, pady=(0, 4))

        self.play_btn = ttk.Button(c_row1, text="▶ PLAY", style="Action.TButton", command=self.toggle_play)
        self.play_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.pause_btn = ttk.Button(c_row1, text="⏸ PAUSE", command=self.toggle_pause)
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(c_row1, text="Speed:", style="Card.TLabel").pack(side=tk.LEFT, padx=(6, 2))
        self.tempo_label = ttk.Label(c_row1, text="0.15s", style="Card.TLabel", font=("Consolas", 9, "bold"))
        self.tempo_label.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(c_row1, text="-", width=3, command=lambda: self.adjust_tempo(-0.02)).pack(side=tk.LEFT, padx=1)
        ttk.Button(c_row1, text="+", width=3, command=lambda: self.adjust_tempo(0.02)).pack(side=tk.LEFT, padx=1)

        c_row2 = ttk.Frame(ctrl_card, style="Card.TFrame")
        c_row2.pack(fill=tk.X)

        ttk.Label(c_row2, text="Transpose:", style="Card.TLabel").pack(side=tk.LEFT)
        self.pitch_label = ttk.Label(c_row2, text="0 semitones", style="Card.TLabel", font=("Consolas", 9, "bold"))
        self.pitch_label.pack(side=tk.LEFT, padx=6)

        ttk.Button(c_row2, text="# (+1)", width=6, command=lambda: self.adjust_pitch(1)).pack(side=tk.RIGHT, padx=2)
        ttk.Button(c_row2, text="⟲ Reset", width=8, command=lambda: self.adjust_pitch(0, reset=True)).pack(side=tk.RIGHT, padx=2)
        ttk.Button(c_row2, text="♭ (-1)", width=6, command=lambda: self.adjust_pitch(-1)).pack(side=tk.RIGHT, padx=2)

        ttk.Label(main, text="SHEET NOTATION AREA", style="Header.TLabel").pack(anchor=tk.W, pady=(4, 2))
        
        self.sheet_box = tk.Text(main, height=7, bg="#121218", fg="#FFFFFF", insertbackground="#FFFFFF",
                                 bd=1, relief="solid", highlightthickness=0, font=("Consolas", 9), wrap=tk.WORD)
        self.sheet_box.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self.status_var = tk.StringVar(value="Initializing catalog...")
        status_lbl = ttk.Label(main, textvariable=self.status_var, style="Status.TLabel")
        status_lbl.pack(anchor=tk.W)

    def _f8_killswitch_listener(self):
        while True:
            if user32.GetAsyncKeyState(VK_F8) & 0x8000:
                if self.is_playing:
                    self.stop_playback()
                    self._update_status("Emergency Stop Activated (F8)")
                time.sleep(0.3)
            time.sleep(0.05)

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def _init_data_async(self):
        self.pipeline.init_catalog_async(self._update_status)
        self.root.after(0, lambda: self._populate_list(self.pipeline.catalog))

    def _populate_list(self, items):
        self.current_results = items
        self.listbox.delete(0, tk.END)
        for item in items:
            self.listbox.insert(tk.END, item["title"])

    def _on_search(self, *args):
        query = self.search_var.get()
        results = self.pipeline.search_fuzzy(query)
        self._populate_list(results)

    def _on_select_song(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        item = self.current_results[sel[0]]
        self._update_status(f"Fetching '{item['title']}'...")

        def load_task():
            sheet = self.pipeline.fetch_sheet_content(item)
            if sheet:
                self.root.after(0, lambda: self._set_sheet_text(sheet))
                self._update_status(f"Loaded: {item['title']}")
            else:
                self._update_status("Error loading sheet from web!")

        threading.Thread(target=load_task, daemon=True).start()

    def _set_sheet_text(self, text):
        self.sheet_box.delete("1.0", tk.END)
        self.sheet_box.insert("1.0", text)

    def adjust_tempo(self, delta):
        self.tempo = round(max(0.02, min(0.80, self.tempo + delta)), 2)
        self.tempo_label.config(text=f"{self.tempo:.2f}s")

    def adjust_pitch(self, delta, reset=False):
        if reset:
            self.pitch_shift = 0
        else:
            self.pitch_shift = max(-12, min(12, self.pitch_shift + delta))
        self.pitch_label.config(text=f"{self.pitch_shift:+d} semitones")

    def transpose_char(self, char):
        if self.pitch_shift == 0 or char not in PIANO_KEY_MAP:
            return char
        idx = PIANO_KEY_MAP.find(char)
        if idx == -1:
            return char
        new_idx = max(0, min(len(PIANO_KEY_MAP) - 1, idx + self.pitch_shift))
        return PIANO_KEY_MAP[new_idx]

    def parse_sheet_string(self, text):
        tokens = []
        i, n = 0, len(text)
        while i < n:
            char = text[i]
            if char == '[':
                chord = []
                i += 1
                while i < n and text[i] != ']':
                    if text[i] in PIANO_KEY_MAP:
                        chord.append(text[i])
                    i += 1
                if chord:
                    tokens.append({'type': 'chord', 'keys': chord})
            elif char == '{':
                i += 1
                while i < n and text[i] != '}':
                    if text[i] in PIANO_KEY_MAP:
                        tokens.append({'type': 'fast_key', 'key': text[i]})
                    i += 1
            elif char == ' ':
                tokens.append({'type': 'pause'})
            elif char in ('\n', '|', '-'):
                tokens.append({'type': 'line_pause'})
            elif char in PIANO_KEY_MAP:
                tokens.append({'type': 'key', 'key': char})
            i += 1
        return tokens

    def stop_playback(self):
        self.is_playing = False
        self.is_paused = False
        self.root.after(0, lambda: self.play_btn.config(text="▶ PLAY"))
        self.root.after(0, lambda: self.pause_btn.config(text="⏸ PAUSE"))

    def toggle_play(self):
        if self.is_playing:
            self.stop_playback()
            self._update_status("Status: Stopped")
        else:
            sheet_content = self.sheet_box.get("1.0", tk.END).strip()
            if not sheet_content:
                messagebox.showwarning("Warning", "Sheet area is empty! Load a song or paste a sheet.")
                return
            self.is_playing = True
            self.is_paused = False
            self.play_btn.config(text="⏹ STOP")

            self._update_status("Focusing Roblox window...")
            focus_roblox_or_alt_tab()

            threading.Thread(target=self._playback_worker, args=(sheet_content,), daemon=True).start()

    def toggle_pause(self):
        if not self.is_playing:
            return
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_btn.config(text="▶ RESUME")
            self._update_status("Status: Paused")
        else:
            self.pause_btn.config(text="⏸ PAUSE")
            self._update_status("Status: Playing...")

    def _playback_worker(self, sheet_text):
        time.sleep(0.5)
        self._update_status("Status: Playing in Roblox (Press F8 to Stop)...")
        tokens = self.parse_sheet_string(sheet_text)

        for token in tokens:
            if not self.is_playing:
                break

            while self.is_paused and self.is_playing:
                time.sleep(0.05)

            if not self.is_playing:
                break

            ttype = token['type']
            if ttype == 'key':
                ch = self.transpose_char(token['key'])
                self.driver.press_char(ch)
                time.sleep(self.tempo)
            elif ttype == 'fast_key':
                ch = self.transpose_char(token['key'])
                self.driver.press_char(ch)
                time.sleep(self.tempo * 0.35)
            elif ttype == 'chord':
                chars = [self.transpose_char(k) for k in token['keys']]
                self.driver.press_chord(chars)
                time.sleep(self.tempo)
            elif ttype == 'pause':
                time.sleep(self.tempo * 0.6)
            elif ttype == 'line_pause':
                time.sleep(self.tempo * 1.2)

        self.stop_playback()
        self._update_status("Status: Finished Playing")


if __name__ == "__main__":
    root = tk.Tk()
    app = PianoAutoplayerGUI(root)
    root.mainloop()