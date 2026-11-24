import json, os, re, threading, datetime
import requests
import phonenumbers
from phonenumbers import carrier, geocoder, timezone, number_type, region_code_for_number
from kivy.app import App
from kivy.clock import Clock
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

UA = ("Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

REGISTROS = {
    "PE": ["OSIPTEL titularidad|https://checatuslineas.osiptel.gob.pe",
           "DNI Peru|https://eldni.com/pe/buscar-datos-por-dni"],
    "AR": ["Padron|https://www.argentina.gob.ar/padron"],
    "CL": ["Registro Civil|https://www.registrocivil.cl"],
    "CO": ["Registraduria|https://www.registraduria.gov.co"],
    "MX": ["CURP|https://www.gob.mx/curp"],
    "ES": ["FNMT|https://www.sede.fnmt.gob.es"],
    "BR": ["CPF|https://www.gov.br/receitafederal"],
    "EC": ["Registro Civil|https://www.registrocivil.gob.ec"],
    "BO": ["SEGIP|https://www.segip.gob.bo"],
    "US": ["FastPeopleSearch|https://www.fastpeoplesearch.com"],
}
GLOBAL = ["EPIEOS Google|https://epieos.com",
          "HaveIBeenPwned|https://haveibeenpwned.com",
          "LeakCheck|https://leakcheck.io"]

def parse(raw, region):
    raw = re.sub(r"[^\d+]", "", raw)
    n = phonenumbers.parse(raw, region or "PE")
    if not phonenumbers.is_valid_number(n):
        raise ValueError("numero invalido")
    return n

def e164(n):
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)

def limpia(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()

# ---------------- fases ----------------

def f_meta(n):
    return {"valido": True, "e164": e164(n), "pais": region_code_for_number(n),
            "tipo": str(number_type(n)),
            "operador_original": carrier.name_for_number(n, "es"),
            "region": geocoder.description_for_number(n, "es"),
            "zona_horaria": list(timezone.time_zones_for_number(n))}

def f_carrier(n):
    e = e164(n).lstrip("+")
    out = {}
    try:
        r = requests.post("https://freecarrierlookup.com/index.php",
                          data={"cc": e[:-10] or "1", "phonenum": e[-10:], "submitted": "1"},
                          headers={"User-Agent": UA,
                                   "Referer": "https://freecarrierlookup.com/"}, timeout=25)
        t = limpia(r.text)
        m = re.search(r"Carrier:\s*([^|]{2,60}?)\s*Line Type:\s*(\w+)", t)
        if m:
            out["operador"] = m.group(1)
            out["tipo_linea"] = m.group(2)
    except Exception as ex:
        out["error_freecarrier"] = str(ex)
    if "operador" not in out:
        try:
            r = requests.get("https://www.numlookup.com/", params={"number": e164(n)},
                             headers={"User-Agent": UA}, timeout=25)
            t = limpia(r.text)
            for pat, k in ((r"Carrier\s*:?\s*([A-Za-z0-9 .&\-]{2,40})", "operador"),
                           (r"(Mobile|Landline|Fixed)", "tipo_linea")):
                m = re.search(pat, t)
                if m:
                    out[k] = m.group(1)
        except Exception as ex:
            out["error_numlookup"] = str(ex)
    return out

def f_apps(n):
    e = e164(n).lstrip("+")
    out = {}
    try:
        h = requests.get(f"https://wa.me/{e}", headers={"User-Agent": UA}, timeout=25).text
        m = h.split('og:title" content="')
        tit = m[1].split('"')[0] if len(m) > 1 else ""
        out["whatsapp"] = {"nombre_publico": None if tit in ("", "+" + e, e) else tit,
                           "business": "wa.me/message" in h}
    except Exception as ex:
        out["whatsapp"] = {"error": str(ex)}
    try:
        h = requests.get(f"https://t.me/+{e}", headers={"User-Agent": UA}, timeout=25).text
        out["telegram"] = {"existe": "tgme_page_title" in h}
    except Exception as ex:
        out["telegram"] = {"error": str(ex)}
    try:
        r = requests.post("https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/",
                          data={"email": "", "phone_number": e, "username": "",
                                "first_name": "", "opt_into_one_tap": "false"},
                          headers={"User-Agent": UA, "x-ig-app-id": "936619743392459",
                                   "x-requested-with": "XMLHttpRequest",
                                   "Referer": "https://www.instagram.com/accounts/emailsignup/"},
                          timeout=25)
        out["instagram"] = {"registrado": bool(r.json().get("errors", {}).get("phone_number"))}
    except Exception as ex:
        out["instagram"] = {"error": str(ex)}
    return out

def f_truecaller(n):
    e = e164(n).lstrip("+")
    cc = (region_code_for_number(n) or "pe").lower()
    try:
        r = requests.get(f"https://www.truecaller.com/search/{cc}/{e}",
                         headers={"User-Agent": UA, "Accept-Language": "es-PE"}, timeout=30)
        if r.status_code == 403:
            return {"error": "bloqueo Cloudflare"}
        m = re.search(r'"name"\s*:\s*"([^"]{2,80})"', r.text)
        return {"nombre": m.group(1) if m else None,
                "http": r.status_code}
    except Exception as ex:
        return {"error": str(ex)}

def f_syncme(n):
    try:
        r = requests.get("https://sync.me/search/", params={"number": e164(n)},
                         headers={"User-Agent": UA}, timeout=25)
        m = re.search(r'itemprop="name"[^>]*>([^<]{2,80})', r.text)
        return {"nombre": m.group(1).strip() if m else None}
    except Exception as ex:
        return {"error": str(ex)}

def f_dni(dni):
    try:
        r = requests.post("https://eldni.com/pe/buscar-datos-por-dni",
                          data={"dni": dni},
                          headers={"User-Agent": UA, "Referer": "https://eldni.com/"}, timeout=30)
        celdas = [c.strip() for c in re.findall(r"<td[^>]*>([^<]{1,120})</td>", r.text)]
        return {"celdas": celdas, "html_len": len(r.text)}
    except Exception as ex:
        return {"error": str(ex)}

def f_dorks(n):
    e = e164(n).lstrip("+")
    nat = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.NATIONAL)
    qs = [f'"{e}"', f'"{nat}"', f'"{nat}" site:facebook.com',
          f'"{nat}" site:instagram.com', f'"{nat}" site:linkedin.com',
          f'"{nat}" filetype:pdf', f'"{nat}" (dni OR ruc)']
    return [{"q": q, "url": "https://www.google.com/search?q=" + requests.utils.quote(q)}
            for q in qs]

# ---------------- UI ----------------

class UI(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=8, spacing=6, **kw)
        self.store = JsonStore(os.path.join(App.get_running_app().user_data_dir, "k.json"))
        self.log, self.pais = [], "PE"

        fila = BoxLayout(size_hint_y=None, height=48, spacing=6)
        self.num = TextInput(hint_text="+51 9XX XXX XXX", multiline=False)
        self.reg = TextInput(text="PE", multiline=False, size_hint_x=0.2)
        fila.add_widget(self.num); fila.add_widget(self.reg)
        self.add_widget(fila)

        self.add_widget(Button(text="RECOPILAR TODO", size_hint_y=None, height=52,
                               background_color=(0.2, 0.6, 0.3, 1), on_release=self.recopilar))

        g = GridLayout(cols=3, size_hint_y=None, height=90, spacing=4)
        for t, fn in (("Metadatos", self.solo_meta), ("Apps", self.solo_apps),
                      ("Dorks", self.dorks), ("DNI", self.dni),
                      ("Registros", self.registros), ("Limpiar", self.limpiar)):
            b = Button(text=t, font_size=12); b.bind(on_release=fn); g.add_widget(b)
        self.add_widget(g)

        self.out = Label(text="Listo.", size_hint_y=None, halign="left", valign="top", font_size=11)
        self.out.bind(width=lambda *_: setattr(self.out, "text_size", (self.out.width, None)))
        self.out.bind(texture_size=lambda *_: setattr(self.out, "height", self.out.texture_size[1]))
        sc = ScrollView(); sc.add_widget(self.out); self.add_widget(sc)

        gb = GridLayout(cols=2, size_hint_y=None, height=46, spacing=4)
        for t, fn in (("Guardar", self.guardar), ("Compartir", self.compartir)):
            b = Button(text=t, font_size=12); b.bind(on_release=fn); gb.add_widget(b)
        self.add_widget(gb)

    def w(self, k, v):
        self.log.append({k: v})
        self.out.text = "\n\n".join(json.dumps(o, ensure_ascii=False, indent=2) for o in self.log)

    def _n(self):
        n = parse(self.num.text, self.reg.text.strip().upper())
        self.pais = region_code_for_number(n) or self.reg.text.strip().upper()
        return n

    def hilo(self, fn, *a):
        def job():
            try: r = fn(*a)
            except Exception as ex: r = {"error": str(ex)}
            Clock.schedule_once(lambda dt: self.w(fn.__name__, r))
        threading.Thread(target=job, daemon=True).start()

    def recopilar(self, *_):
        try: n = self._n()
        except Exception as ex: return self.w("validacion", {"error": str(ex)})
        self.hilo(f_meta, n)
        self.hilo(f_carrier, n)
        self.hilo(f_apps, n)
        self.hilo(f_truecaller, n)
        self.hilo(f_syncme, n)
        self.hilo(f_dorks, n)
        self.registros()

    def solo_meta(self, *_):
        try: self.hilo(f_meta, self._n())
        except Exception as ex: self.w("validacion", {"error": str(ex)})

    def solo_apps(self, *_):
        try: self.hilo(f_apps, self._n())
        except Exception as ex: self.w("validacion", {"error": str(ex)})

    def dorks(self, *_):
        try: self.hilo(f_dorks, self._n())
        except Exception as ex: self.w("validacion", {"error": str(ex)})

    def dni(self, *_):
        self.hilo(f_dni, re.sub(r"\D", "", self.num.text))

    def registros(self, *_):
        for x in REGISTROS.get(self.pais, []) + GLOBAL:
            nom, url = x.split("|")
            self.w("registro", {"nombre": nom, "url": url})

    def _texto(self):
        return "\n\n".join(json.dumps(o, ensure_ascii=False, indent=2) for o in self.log)

    def guardar(self, *_):
        d = os.path.join(App.get_running_app().user_data_dir, "informes")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        open(f, "w", encoding="utf-8").write(self._texto())
        self.w("guardado", f)

    def compartir(self, *_):
        from jnius import autoclass
        I = autoclass("android.content.Intent"); PA = autoclass("org.kivy.android.PythonActivity")
        i = I(); i.setAction(I.ACTION_SEND)
        i.putExtra(I.EXTRA_TEXT, self._texto() or "sin datos"); i.setType("text/plain")
        PA.mActivity.startActivity(I.createChooser(i, "Compartir informe"))

    def limpiar(self, *_):
        self.log = []; self.out.text = "Listo."

class PG(App):
    def build(self):
        self.title = "PhoneGene"; return UI()

if __name__ == "__main__":
    PG().run()
