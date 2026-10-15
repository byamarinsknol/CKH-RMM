"""Gedeelde code voor klantdashboards met Google Ads + GA4 (live via de Windsor.ai API).

Elke klant heeft een eigen klein bestand (bijvoorbeeld ckh_app.py) dat run(CONFIG) aanroept.
"""
import hmac
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = "https://connectors.windsor.ai/{connector}"


# ---------------------------------------------------------------------------
# Opmaak
# ---------------------------------------------------------------------------
def nl(value, decimals=0):
    if value is None or pd.isna(value):
        return "-"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def eur(value, decimals=2):
    return "-" if value is None or pd.isna(value) else f"€ {nl(value, decimals)}"


def pct(value):
    return "-" if value is None or pd.isna(value) else f"{nl(value * 100, 1)}%"


def change(cur, prev):
    if cur is None or prev is None or not prev or pd.isna(cur) or pd.isna(prev):
        return None
    return f"{nl((cur - prev) / prev * 100, 1)}%"


def leads_fmt(value):
    return nl(value, 0 if float(value).is_integer() else 1)


# ---------------------------------------------------------------------------
# Data ophalen (alleen het account van deze klant, anders stoppen)
# ---------------------------------------------------------------------------
def digits(value):
    return re.sub(r"\D", "", str(value or ""))


TEXT_COLS = {"date", "campaign", "campaign_type", "account_id", "account_name", "conversion_action_name",
             "keyword_text", "keyword_match_type", "event_name", "session_source_medium"}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch(connector, fields, date_preset, account):
    params = {
        "api_key": st.secrets["WINDSOR_API_KEY"],
        "date_preset": date_preset,
        "fields": ",".join(list(fields) + ["account_id"]),
    }
    response = requests.get(API_URL.format(connector=connector), params=params, timeout=180)
    response.raise_for_status()
    body = response.json()
    rows = body.get("data", []) if isinstance(body, dict) else body
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=list(fields))
    if "account_id" not in df.columns:
        # Liever niets tonen dan per ongeluk data van andere klanten
        raise RuntimeError("Windsor.ai gaf geen account-ID terug, daarom wordt er niets getoond.")
    df = df[df["account_id"].map(digits) == account].copy()
    for col in df.columns:
        if col not in TEXT_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def is_form(name):
    n = str(name).lower()
    return ("formulier" in n or "form_" in n) and ("verstuurd" in n)


def is_ads_form(name):
    # Alleen de Google Ads-tags tellen, de geimporteerde GA4-doelen zijn dubbel
    n = str(name).lower()
    return "formulier" in n and "ads tag" in n


def is_call(name):
    n = str(name).lower()
    return "clicks to call" in n or "telefoonnummer" in n or "vaste_nummer" in n


def lead_type_ads(name):
    if is_ads_form(name):
        return "forms"
    if is_call(name):
        return "calls"
    return None


def lead_type_ga4(name):
    if is_form(name):
        return "forms"
    if is_call(name):
        return "calls"
    return None


def pivot_leads(df, index, value):
    """Leads per type (forms/calls) als kolommen; leeg als er niets te tellen is."""
    sub = df[df["type"].notna()] if not df.empty and "type" in df.columns else pd.DataFrame()
    if sub.empty:
        return pd.DataFrame()
    return sub.pivot_table(index=index, columns="type", values=value, aggfunc="sum", fill_value=0)


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------
def style(cfg):
    p, a, band = cfg["primary"], cfg["accent"], cfg.get("logo_background", cfg["primary"])
    st.markdown(
        f"""
        <style>
          .block-container {{max-width: 1180px; padding-top: 1.2rem;}}
          [data-testid="stMetricValue"] {{font-variant-numeric: tabular-nums;}}
          .brandbar {{display:flex; align-items:center; justify-content:space-between; gap:16px;
                      background:{band}; border-radius:14px; padding:14px 22px; margin-bottom:18px;}}
          .brandbar img {{max-height:54px; max-width:260px; object-fit:contain;}}
          .brandbar .t {{color:{cfg.get("logo_text_color", "#FFFFFF")}; text-align:right; font-size:0.95rem; opacity:.9}}
          h2, h3 {{color:{p};}}
          .stTabs [aria-selected="true"] {{color:{p} !important; border-bottom-color:{p} !important;}}
          div.stButton > button {{border-color:{p}; color:{p};}}
          div.stButton > button:hover {{background:{p}; color:#fff;}}
          .lead-kpi [data-testid="stMetricValue"] {{color:{p};}}
          .note {{font-size:0.85rem; opacity:.75;}}
          .accentdot {{display:inline-block;width:10px;height:10px;border-radius:2px;background:{a};margin-right:6px}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def password_gate(cfg):
    """Het dashboard is altijd beveiligd: zonder ingesteld wachtwoord komt niemand erin."""
    juist = str(st.secrets.get("DASHBOARD_PASSWORD", "")).strip()
    if not juist:
        st.error("Dit dashboard is nog niet beveiligd. Voeg DASHBOARD_PASSWORD toe bij Settings, Secrets "
                 "in Streamlit. Zonder wachtwoord wordt er niets getoond.")
        st.stop()
    if st.session_state.get("ingelogd"):
        return
    st.markdown(f'<div class="brandbar"><img src="{cfg["logo_url"]}" alt="{cfg["name"]}"></div>',
                unsafe_allow_html=True)
    wachtwoord = st.text_input("Wachtwoord", type="password")
    if wachtwoord:
        if hmac.compare_digest(wachtwoord.strip(), juist):
            st.session_state["ingelogd"] = True
            st.rerun()
        else:
            st.error("Onjuist wachtwoord.")
    st.stop()


def run(cfg):
    st.set_page_config(page_title=f"{cfg['name']} - Online resultaten", page_icon="📈", layout="wide")
    style(cfg)
    if "WINDSOR_API_KEY" not in st.secrets:
        st.error("Geen Windsor.ai API-sleutel gevonden. Voeg WINDSOR_API_KEY toe bij Settings, Secrets.")
        st.stop()
    password_gate(cfg)

    st.markdown(
        f'<div class="brandbar"><img src="{cfg["logo_url"]}" alt="{cfg["name"]}">'
        f'<div class="t">Online resultaten<br>Google Ads en website</div></div>',
        unsafe_allow_html=True,
    )
    c_left, c_right = st.columns([3, 2])
    with c_right:
        period = st.segmented_control("Periode", [7, 30, 90], default=30,
                                      format_func=lambda d: f"{d} dagen", label_visibility="collapsed") or 30
    with c_left:
        if st.button("Nu verversen"):
            st.cache_data.clear()
            st.rerun()

    ads_acc, ga4_acc = cfg["ads_account"], cfg["ga4_account"]
    try:
        with st.spinner("Gegevens ophalen..."):
            ads = fetch("google_ads", ("date", "campaign", "campaign_type", "spend", "impressions", "clicks"),
                        "last_90d", ads_acc)
            conv = fetch("google_ads", ("date", "campaign", "conversion_action_name", "all_conversions"),
                         "last_90d", ads_acc)
            ga_sessions = fetch("googleanalytics4", ("date", "session_source_medium", "sessions",
                                                     "engaged_sessions"), "last_90d", ga4_acc)
            ga_events = fetch("googleanalytics4", ("date", "session_source_medium", "event_name",
                                                   "event_count"), "last_90d", ga4_acc)
            kw_perf = fetch("google_ads", ("keyword_text", "keyword_match_type", "impressions", "clicks", "spend"),
                            f"last_{period}d", ads_acc)
            kw_conv = fetch("google_ads", ("keyword_text", "keyword_match_type", "conversion_action_name",
                                           "all_conversions"), f"last_{period}d", ads_acc)
    except Exception as exc:  # noqa: BLE001
        st.error(f"De gegevens konden niet worden opgehaald: {exc}")
        st.stop()

    if not conv.empty:
        conv["type"] = conv["conversion_action_name"].map(lead_type_ads)
    if not ga_events.empty:
        ga_events["type"] = ga_events["event_name"].map(lead_type_ga4)

    dates = pd.concat([d["date"] for d in (ads, ga_sessions) if not d.empty])
    if dates.empty:
        st.info("Nog geen gegevens gevonden voor de afgelopen 90 dagen.")
        st.stop()
    end = dates.max()
    start = end - pd.Timedelta(days=period - 1)
    p_end, p_start = start - pd.Timedelta(days=1), start - pd.Timedelta(days=period)

    def win(df, a, b):
        return df if df.empty else df[(df["date"] >= a) & (df["date"] <= b)]

    calls_count = cfg["calls_are_leads"]
    st.caption(f"{start:%d-%m-%Y} t/m {end:%d-%m-%Y}, bijgewerkt om {datetime.now():%H:%M}")

    # ------------------------------------------------------------------ Google Ads
    def ads_totals(a, b):
        s = win(ads, a, b)
        c = win(conv, a, b)
        forms = float(c.loc[c["type"] == "forms", "all_conversions"].sum()) if not c.empty else 0.0
        calls = float(c.loc[c["type"] == "calls", "all_conversions"].sum()) if not c.empty else 0.0
        spend = float(s["spend"].sum()) if not s.empty else 0.0
        clicks = float(s["clicks"].sum()) if not s.empty else 0.0
        impr = float(s["impressions"].sum()) if not s.empty else 0.0
        leads = forms + (calls if calls_count else 0)
        return {"forms": forms, "calls": calls, "leads": leads, "spend": spend, "clicks": clicks,
                "impr": impr, "cpl": spend / leads if leads else None,
                "ctr": clicks / impr if impr else None, "cr": leads / clicks if clicks else None}

    now = ads_totals(start, end)
    has_prev = not ads.empty and ads["date"].min() <= p_start
    prev = ads_totals(p_start, p_end) if has_prev else None

    def pv(k):
        return prev[k] if prev else None

    st.subheader("Google Ads")
    cols = st.columns(6)
    if calls_count:
        items = [
            ("Leads totaal", leads_fmt(now["leads"]), change(now["leads"], pv("leads")), "normal", True),
            ("Formulieren", leads_fmt(now["forms"]), change(now["forms"], pv("forms")), "normal", True),
            ("Klik om te bellen", leads_fmt(now["calls"]), change(now["calls"], pv("calls")), "normal", True),
            ("Kosten per lead", eur(now["cpl"]), change(now["cpl"], pv("cpl")), "inverse", False),
            ("Uitgaven", eur(now["spend"], 0), change(now["spend"], pv("spend")), "off", False),
            ("Klikken", nl(now["clicks"]), change(now["clicks"], pv("clicks")), "normal", False),
        ]
    else:
        items = [
            ("Formulierleads", leads_fmt(now["forms"]), change(now["forms"], pv("forms")), "normal", True),
            ("Kosten per lead", eur(now["cpl"]), change(now["cpl"], pv("cpl")), "inverse", False),
            ("Conversieratio", pct(now["cr"]), change(now["cr"], pv("cr")), "normal", False),
            ("Uitgaven", eur(now["spend"], 0), change(now["spend"], pv("spend")), "off", False),
            ("Klikken", nl(now["clicks"]), change(now["clicks"], pv("clicks")), "normal", False),
            ("CTR", pct(now["ctr"]), change(now["ctr"], pv("ctr")), "normal", False),
        ]
    for col, (label, val, dlt, color, is_lead) in zip(cols, items):
        with col:
            if is_lead:
                st.markdown('<div class="lead-kpi">', unsafe_allow_html=True)
            st.metric(label, val, dlt, delta_color=color)
            if is_lead:
                st.markdown("</div>", unsafe_allow_html=True)

    # Grafiek: leads per dag + uitgaven
    days = pd.date_range(start, end)
    c_now = win(conv, start, end)
    s_now = win(ads, start, end)
    forms_d = (c_now[c_now["type"] == "forms"].groupby("date")["all_conversions"].sum()
               .reindex(days, fill_value=0)) if not c_now.empty else pd.Series(0, index=days)
    calls_d = (c_now[c_now["type"] == "calls"].groupby("date")["all_conversions"].sum()
               .reindex(days, fill_value=0)) if not c_now.empty else pd.Series(0, index=days)
    spend_d = s_now.groupby("date")["spend"].sum().reindex(days, fill_value=0) if not s_now.empty \
        else pd.Series(0, index=days)
    fig = go.Figure()
    fig.add_bar(x=days, y=forms_d, name="Formulieren", marker_color=cfg["primary"])
    if calls_count:
        fig.add_bar(x=days, y=calls_d, name="Klik om te bellen", marker_color=cfg["accent"])
    gran = st.segmented_control("Weergave", ["Per week", "Per dag"], default="Per week",
                                label_visibility="collapsed", key="gran") or "Per week"
    if gran == "Per week":
        def weekly(series):
            out = series.groupby(series.index.to_period("W-SUN")).sum()
            out.index = out.index.start_time
            return out
        forms_d, calls_d, spend_d = weekly(forms_d), weekly(calls_d), weekly(spend_d)
        days = forms_d.index
    leads_d = forms_d + (calls_d if calls_count else 0)
    cpl_d = (spend_d / leads_d.where(leads_d > 0)).round(2)
    fig.add_scatter(x=days, y=cpl_d, name="Kosten per lead", mode="lines+markers", yaxis="y2",
                    connectgaps=True, line=dict(color="#8A94A0", width=2, shape="spline"),
                    marker=dict(size=6))
    fig.update_layout(
        barmode="stack", height=330, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0),
        yaxis=dict(title="Leads", rangemode="tozero"),
        yaxis2=dict(title="Kosten per lead (€)", overlaying="y", side="right", rangemode="tozero", showgrid=False),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")

    # ------------------------------------------------------------------ Zoekwoorden
    st.subheader("Best presterende zoekwoorden")
    if kw_perf.empty and kw_conv.empty:
        st.info("Geen zoekwoorddata in deze periode.")
    else:
        keys = ["keyword_text", "keyword_match_type"]
        perf = kw_perf.groupby(keys)[["impressions", "clicks", "spend"]].sum() if not kw_perf.empty \
            else pd.DataFrame(columns=["impressions", "clicks", "spend"])
        kc = kw_conv.copy()
        if not kc.empty:
            kc["type"] = kc["conversion_action_name"].map(lead_type_ads)
        kc = pivot_leads(kc, keys, "all_conversions")
        kw = perf.join(kc, how="outer") if not kc.empty else perf
        kw = kw.fillna(0).reset_index()
        for col in ("forms", "calls"):
            if col not in kw.columns:
                kw[col] = 0.0
        kw["leads"] = kw["forms"] + (kw["calls"] if calls_count else 0)
        kw["cpl"] = kw["spend"] / kw["leads"].where(kw["leads"] > 0)
        kw["match"] = kw["keyword_match_type"].map(
            {"EXACT": "Exact", "PHRASE": "Woordgroep", "BROAD": "Breed"}).fillna(kw["keyword_match_type"])
        kw = kw.sort_values(["leads", "cpl", "clicks"], ascending=[False, True, False])
        show_all = st.toggle("Alle zoekwoorden tonen", value=False)
        view = kw if show_all else kw[kw["leads"] > 0].head(10)
        if view.empty:
            st.info("Geen zoekwoorden met leads in deze periode.")
        else:
            columns = ["keyword_text", "match", "clicks", "spend", "forms"] + (["calls"] if calls_count else []) \
                + ["leads", "cpl"]
            st.dataframe(
                view[columns], hide_index=True, width="stretch",
                column_config={
                    "keyword_text": st.column_config.TextColumn("Zoekwoord", width="large"),
                    "match": st.column_config.TextColumn("Zoektype"),
                    "clicks": st.column_config.NumberColumn("Klikken", format="%d"),
                    "spend": st.column_config.NumberColumn("Kosten", format="€ %.2f"),
                    "forms": st.column_config.NumberColumn("Formulieren", format="%.1f"),
                    "calls": st.column_config.NumberColumn("Bellen", format="%.1f"),
                    "leads": st.column_config.NumberColumn("Leads", format="%.1f"),
                    "cpl": st.column_config.NumberColumn("Kosten per lead", format="€ %.2f"),
                },
            )
        st.markdown('<p class="note">Performance Max-campagnes werken zonder zoekwoorden en staan daarom niet '
                    'in deze lijst. Halve leads ontstaan doordat Google een lead over meerdere klikken verdeelt.</p>',
                    unsafe_allow_html=True)

    # ------------------------------------------------------------------ Campagnes
    st.subheader("Campagnes")
    if s_now.empty:
        st.info("Geen campagnedata in deze periode.")
    else:
        camp = s_now.groupby(["campaign", "campaign_type"])[["spend", "impressions", "clicks"]].sum().reset_index()
        cc = pivot_leads(c_now, "campaign", "all_conversions")
        if not cc.empty:
            camp = camp.merge(cc, left_on="campaign", right_index=True, how="left")
        for col in ("forms", "calls"):
            if col not in camp.columns:
                camp[col] = 0.0
        camp = camp.fillna(0)
        camp["leads"] = camp["forms"] + (camp["calls"] if calls_count else 0)
        camp["cpl"] = camp["spend"] / camp["leads"].where(camp["leads"] > 0)
        camp["campaign_type"] = camp["campaign_type"].map({
            "SEARCH": "Zoeken", "PERFORMANCE_MAX": "Performance Max", "DEMAND_GEN": "Demand Gen",
            "DISPLAY": "Display", "VIDEO": "Video"}).fillna(camp["campaign_type"])
        camp = camp.sort_values("spend", ascending=False)
        columns = ["campaign", "campaign_type", "spend", "clicks", "forms"] + (["calls"] if calls_count else []) \
            + ["leads", "cpl"]
        st.dataframe(
            camp[columns], hide_index=True, width="stretch",
            column_config={
                "campaign": st.column_config.TextColumn("Campagne", width="large"),
                "campaign_type": st.column_config.TextColumn("Type"),
                "spend": st.column_config.NumberColumn("Kosten", format="€ %.2f"),
                "clicks": st.column_config.NumberColumn("Klikken", format="%d"),
                "forms": st.column_config.NumberColumn("Formulieren", format="%.1f"),
                "calls": st.column_config.NumberColumn("Bellen", format="%.1f"),
                "leads": st.column_config.NumberColumn("Leads", format="%.1f"),
                "cpl": st.column_config.NumberColumn("Kosten per lead", format="€ %.2f"),
            },
        )

    # ------------------------------------------------------------------ Website (GA4)
    st.subheader("Website, alle kanalen")
    gs, ge = win(ga_sessions, start, end), win(ga_events, start, end)
    gs_p, ge_p = win(ga_sessions, p_start, p_end), win(ga_events, p_start, p_end)
    has_prev_ga = not ga_sessions.empty and ga_sessions["date"].min() <= p_start

    def ga_tot(s, e):
        sessions = float(s["sessions"].sum()) if not s.empty else 0.0
        engaged = float(s["engaged_sessions"].sum()) if not s.empty else 0.0
        forms = float(e.loc[e["type"] == "forms", "event_count"].sum()) if not e.empty else 0.0
        calls = float(e.loc[e["type"] == "calls", "event_count"].sum()) if not e.empty else 0.0
        return {"sessions": sessions, "eng": engaged / sessions if sessions else None, "forms": forms,
                "calls": calls}

    g, gp = ga_tot(gs, ge), (ga_tot(gs_p, ge_p) if has_prev_ga else None)

    def gpv(k):
        return gp[k] if gp else None

    w = st.columns(4)
    w[0].metric("Sessies", nl(g["sessions"]), change(g["sessions"], gpv("sessions")))
    w[1].metric("Betrokken sessies", pct(g["eng"]), change(g["eng"], gpv("eng")))
    w[2].metric("Formulieren (website)", nl(g["forms"]), change(g["forms"], gpv("forms")))
    w[3].metric("Klik op telefoonnummer", nl(g["calls"]), change(g["calls"], gpv("calls")))

    if not gs.empty:
        src = "session_source_medium"
        ch_s = gs.groupby(src)["sessions"].sum()
        ch_e = pivot_leads(ge, src, "event_count")
        ch = pd.DataFrame({"sessions": ch_s})
        if not ch_e.empty:
            ch = ch.join(ch_e, how="outer")
        ch = ch.fillna(0)
        for col in ("forms", "calls"):
            if col not in ch.columns:
                ch[col] = 0.0
        ch.index.name = src
        ch = ch.reset_index()
        ch["is_ads"] = ch[src].str.replace(" ", "").str.lower() == "google/cpc"

        # Aandeel van Google Ads
        ad, tt = ch[ch["is_ads"]][["sessions", "forms", "calls"]].sum(), ch[["sessions", "forms", "calls"]].sum()
        ad_leads = ad["forms"] + (ad["calls"] if calls_count else 0)
        tt_leads = tt["forms"] + (tt["calls"] if calls_count else 0)
        with st.container(border=True):
            st.markdown("#### Wat Google Ads bijdraagt aan de website")
            if tt_leads:
                soort = "websiteleads (formulieren en telefoonklikken)" if calls_count else "formulieren op de website"
                st.markdown(
                    f"Google Ads was goed voor **{pct(ad_leads / tt_leads)}** van alle {soort}: "
                    f"{nl(ad_leads)} van de {nl(tt_leads)}. Daarnaast kwam "
                    f"{pct(ad['sessions'] / tt['sessions']) if tt['sessions'] else '-'} van alle bezoeken via de advertenties.")
            rows = [("Sessies", "sessions"), ("Formulieren", "forms")] + ([("Telefoonklikken", "calls")] if calls_count else [])
            labels = [r[0] for r in rows]
            share = [ad[k] / tt[k] * 100 if tt[k] else 0 for _, k in rows]
            sfig = go.Figure()
            sfig.add_bar(y=labels, x=share, orientation="h", name="Google Ads (google / cpc)",
                         marker_color=cfg["primary"], customdata=[ad[k] for _, k in rows],
                         hovertemplate="%{x:.1f}% (%{customdata:.0f})<extra>Google Ads</extra>")
            sfig.add_bar(y=labels, x=[100 - v if tt[k] else 0 for v, (_, k) in zip(share, rows)], orientation="h",
                         name="Alle andere bronnen", marker_color="#C9D1D9",
                         customdata=[tt[k] - ad[k] for _, k in rows],
                         hovertemplate="%{x:.1f}% (%{customdata:.0f})<extra>Andere bronnen</extra>")
            sfig.update_layout(barmode="stack", height=60 + 45 * len(rows), margin=dict(l=10, r=10, t=10, b=10),
                               xaxis=dict(range=[0, 100], ticksuffix="%", showgrid=False),
                               yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.25, x=0),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(sfig, width="stretch")

        ch = ch.sort_values("sessions", ascending=False)
        if len(ch) > 10:
            rest = ch.iloc[10:][["sessions", "forms", "calls"]].sum()
            ch = pd.concat([ch.iloc[:10], pd.DataFrame([{src: "Overige bronnen", "is_ads": False, **rest}])])
        ch[src] = [f"{x} (Google Ads)" if a else x for x, a in zip(ch[src], ch["is_ads"])]
        st.dataframe(
            ch[[src, "sessions", "forms", "calls"]], hide_index=True, width="stretch",
            column_config={
                src: st.column_config.TextColumn("Sessie bron / medium", width="large"),
                "sessions": st.column_config.NumberColumn("Sessies", format="%d"),
                "forms": st.column_config.NumberColumn("Formulieren", format="%d"),
                "calls": st.column_config.NumberColumn("Klik op telefoonnummer", format="%d"),
            },
        )

    calls_note = ("Klik om te bellen telt het bellen via de advertentie zelf en klikken op het telefoonnummer "
                  "op de website na een advertentieklik. " if calls_count else "")
    st.markdown(
        '<p class="note">Google Ads toont de leads die Google aan de advertenties toeschrijft. '
        + calls_note +
        'Het websiteblok toont alle bezoekers en leads uit Google Analytics, dus ook via Google zonder '
        'advertentie, direct verkeer en social. De cijfers verschillen daardoor van elkaar. '
        'Vergelijking met de periode ervoor van gelijke lengte.</p>',
        unsafe_allow_html=True,
    )
