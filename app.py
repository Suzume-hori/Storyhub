import os, io, hashlib, secrets, sqlite3
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import mm
from reportlab.lib import colors

BASE = Path(__file__).parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
DB_PATH = DATA / "storyverse.db"
UPLOADS.mkdir(parents=True, exist_ok=True)
DATA.mkdir(exist_ok=True)

st.set_page_config(page_title="StoryVerse", page_icon="📖", layout="wide")

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'reader', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stories(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', genre TEXT DEFAULT 'Other',
          cover TEXT DEFAULT '', status TEXT DEFAULT 'draft', comments_enabled INTEGER DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, author_id INTEGER NOT NULL REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS chapters(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT DEFAULT '', position INTEGER DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS comments(
          id INTEGER PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL,
          story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
          user_id INTEGER NOT NULL REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS bookmarks(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
          UNIQUE(user_id, story_id)
        );
        CREATE TABLE IF NOT EXISTS progress(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
          chapter_id INTEGER REFERENCES chapters(id), updated_at TEXT NOT NULL,
          UNIQUE(user_id, story_id)
        );
        CREATE TABLE IF NOT EXISTS goals(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          goal_date TEXT NOT NULL, target_words INTEGER DEFAULT 500, words_written INTEGER DEFAULT 0,
          UNIQUE(user_id, goal_date)
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT DEFAULT '');
        """)
init_db()

def pw_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
    return f"{salt}${digest}"

def pw_check(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        return secrets.compare_digest(pw_hash(password, salt).split("$", 1)[1], digest)
    except Exception:
        return False

def query(sql, params=(), one=False):
    with connect() as c:
        cur = c.execute(sql, params)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows

def execute(sql, params=()):
    with connect() as c:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid

def user():
    uid = st.session_state.get("user_id")
    return query("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None

def is_creator():
    u = user()
    return bool(u and u["role"] == "creator")

def save_upload(upload, prefix):
    if upload is None:
        return ""
    ext = Path(upload.name).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        st.error("Please upload a PNG, JPG, JPEG or WEBP image.")
        return ""
    if upload.size > 5 * 1024 * 1024:
        st.error("Images must be 5 MB or smaller.")
        return ""
    name = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
    path = UPLOADS / name
    image = Image.open(upload).convert("RGB")
    image.save(path, quality=92)
    return str(path.relative_to(BASE))

def img_path(relative):
    p = BASE / (relative or "")
    return p if relative and p.exists() else None

def word_count():
    if not is_creator():
        return 0
    rows = query("SELECT body FROM chapters")
    return sum(len((r["body"] or "").split()) for r in rows)

def pdf_bytes(story):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("BookTitle", parent=styles["Title"], alignment=TA_CENTER,
                                 textColor=colors.HexColor("#26324b"), fontName="Times-Bold")
    chapter_style = ParagraphStyle("Chapter", parent=styles["Heading1"], textColor=colors.HexColor("#26324b"))
    body_style = ParagraphStyle("BookBody", parent=styles["BodyText"], leading=17,
                                fontName="Times-Roman", fontSize=11, spaceAfter=9)
    flow = [Spacer(1, 30*mm), Paragraph(escape(story["title"]), title_style),
            Spacer(1, 8*mm), Paragraph(escape(story["description"] or ""), styles["Italic"]), PageBreak()]
    chapters = query("SELECT * FROM chapters WHERE story_id=? ORDER BY position", (story["id"],))
    for ch in chapters:
        flow += [Paragraph(escape(ch["title"]), chapter_style), Spacer(1, 4*mm)]
        for p in (ch["body"] or "").splitlines():
            if p.strip():
                flow.append(Paragraph(escape(p), body_style))
        flow.append(PageBreak())
    doc.build(flow)
    return buf.getvalue()

# Literary, soft-pastel / midnight-blue visual system
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
:root { --ink:#e9e7f2; --muted:#b9bfd3; --accent:#c8b8e8; }
.stApp { background: radial-gradient(ellipse at 15% 0%, #263b63 0%, #101a31 42%, #0a1020 100%); color:var(--ink); }
.stApp:before { content:"✦   ·      ✧       ·   ✦        ·       ✧"; position:fixed; top:8%; left:8%; color:#c9d7ff66; font-size:22px; letter-spacing:24px; pointer-events:none; }
h1,h2,h3,.serif { font-family:'Playfair Display',serif !important; color:#f0eafa !important; }
p, label, .stMarkdown { color:#e2e2ef; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#192844,#10182b); border-right:1px solid #aab8df33; }
.stButton>button, .stDownloadButton>button { border-radius:12px; border:1px solid #bdaee5; background:#c8b8e8; color:#172039; font-weight:700; }
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"],.stNumberInput input { background:#17233b !important; color:#f4efff !important; border:1px solid #66769b !important; border-radius:10px !important; }
div[data-testid="stForm"] { background:#18264199; padding:1rem; border:1px solid #aebce333; border-radius:16px; }
.story-card { background:linear-gradient(145deg,#243655dd,#17233add); border:1px solid #c5b7e344; border-radius:18px; padding:16px; margin:8px 0; min-height:145px; }
.small-muted { color:#b9bfd3; font-size:.9rem; }
hr { border-color:#aebce333; }
</style>
""", unsafe_allow_html=True)

# User-selectable site background
bg = query("SELECT value FROM settings WHERE key='background'", one=True)
if bg and img_path(bg["value"]):
    import base64
    raw = (BASE / bg["value"]).read_bytes()
    encoded = base64.b64encode(raw).decode()
    ext = Path(bg["value"]).suffix.lower().replace(".", "")
    st.markdown(f'<style>.stApp{{background-image:linear-gradient(#0b1429bb,#0b1429dd),url("data:image/{ext};base64,{encoded}");background-size:cover;background-attachment:fixed;background-position:center;}}</style>', unsafe_allow_html=True)

st.markdown("<div style='text-align:center;padding:.4rem 0 1rem'><div style='font-size:13px;letter-spacing:5px;color:#cbbce9'>A QUIET PLACE FOR STORIES</div><h1 style='font-size:3rem;margin:0'>✦ StoryVerse ✦</h1><div style='color:#bfc9e4;font-family:Playfair Display'>Where every page finds its reader</div></div>", unsafe_allow_html=True)

u = user()
with st.sidebar:
    st.markdown("## ✦ StoryVerse")
    if u:
        st.write(f"Welcome, **{u['username']}**")
        st.caption("Creator account" if u["role"] == "creator" else "Reader account")
    page_options = ["Home", "Search stories"]
    if u:
        page_options += ["My bookshelf", "Writing goals"]
    if is_creator():
        page_options += ["Creator studio", "Background & appearance"]
    page = st.radio("Navigate", page_options, label_visibility="collapsed")
    st.divider()
    if u:
        if st.button("Log out", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    else:
        st.caption("Sign in to save books and join the community.")

# Authentication panel
if not u:
    with st.expander("Reader sign in / create account", expanded=False):
        mode = st.radio("Choose", ["Log in", "Create reader account"], horizontal=True)
        with st.form("auth_form"):
            identity = st.text_input("Username or email")
            email = st.text_input("Email address") if mode == "Create reader account" else ""
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password") if mode == "Create reader account" else ""
            submitted = st.form_submit_button("Continue", use_container_width=True)
        if submitted:
            if mode == "Create reader account":
                if len(identity.strip()) < 3 or len(password) < 8 or password != confirm or not email.strip():
                    st.error("Use a username (3+ characters), valid email, matching passwords and a password of at least 8 characters.")
                elif query("SELECT id FROM users WHERE username=? OR email=?", (identity.strip(), email.strip().lower()), one=True):
                    st.error("That username or email is already registered.")
                else:
                    execute("INSERT INTO users(username,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                            (identity.strip(), email.strip().lower(), pw_hash(password), "reader", datetime.now().isoformat()))
                    st.success("Reader account created. Log in to continue.")
            else:
                found = query("SELECT * FROM users WHERE username=? OR email=?", (identity.strip(), identity.strip().lower()), one=True)
                if found and pw_check(password, found["password_hash"]):
                    st.session_state.user_id = found["id"]
                    st.rerun()
                st.error("Login details were not recognised.")

# First-run creator setup is protected by a one-time setup key in secrets/env.
if not query("SELECT id FROM users WHERE role='creator'", one=True):
    with st.expander("First-time creator setup", expanded=True):
        st.info("Create the single owner account. Set STORYVERSE_SETUP_KEY in your environment or Streamlit secrets before setup.")
        setup_key = st.text_input("Setup key", type="password", key="setup_key")
        with st.form("creator_setup"):
            cu = st.text_input("Creator username")
            ce = st.text_input("Creator email")
            cp = st.text_input("Creator password", type="password")
            cp2 = st.text_input("Confirm creator password", type="password")
            go = st.form_submit_button("Create creator account")
        expected = st.secrets.get("STORYVERSE_SETUP_KEY", os.environ.get("STORYVERSE_SETUP_KEY", ""))
        if go:
            if not expected or not secrets.compare_digest(setup_key, expected):
                st.error("Setup key is missing or incorrect. Configure STORYVERSE_SETUP_KEY first.")
            elif len(cu.strip()) < 3 or len(cp) < 10 or cp != cp2 or not ce.strip():
                st.error("Enter a username, email, and matching password of at least 10 characters.")
            elif query("SELECT id FROM users WHERE username=? OR email=?", (cu.strip(), ce.strip().lower()), one=True):
                st.error("That username or email is already in use.")
            else:
                execute("INSERT INTO users(username,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                        (cu.strip(), ce.strip().lower(), pw_hash(cp), "creator", datetime.now().isoformat()))
                st.success("Creator account created. Sign in using the reader login panel.")
                st.rerun()

def story_tile(s, show_actions=True):
    c1,c2 = st.columns([1,3])
    with c1:
        p = img_path(s["cover"])
        if p: st.image(str(p), use_container_width=True)
        else: st.markdown("<div style='background:linear-gradient(145deg,#a99bc8,#344d75);height:150px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:42px'>✧</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"### {s['title']}")
        st.caption(f"{s['genre']} · {s['status'].title()} · {s['updated_at'][:10]}")
        st.write(s["description"] or "A story waiting to be discovered.")
        chapters = query("SELECT * FROM chapters WHERE story_id=? ORDER BY position", (s["id"],))
        if chapters:
            if st.button("Read story", key=f"read_{s['id']}"):
                st.session_state.open_story = s["id"]
                st.session_state.read_chapter = chapters[0]["id"]
                st.rerun()
        if show_actions and u and s["status"] == "published":
            bookmarked = query("SELECT id FROM bookmarks WHERE user_id=? AND story_id=?", (u["id"],s["id"]), one=True)
            if st.button("Remove from bookshelf" if bookmarked else "＋ Add to bookshelf", key=f"bm_{s['id']}"):
                if bookmarked: execute("DELETE FROM bookmarks WHERE id=?", (bookmarked["id"],))
                else: execute("INSERT OR IGNORE INTO bookmarks(user_id,story_id) VALUES(?,?)",(u["id"],s["id"]))
                st.rerun()
    st.divider()

# Reader view overlay/page
if st.session_state.get("open_story"):
    sid = st.session_state.open_story
    selected_story = query("SELECT * FROM stories WHERE id=?", (sid,), one=True)
    if selected_story and (selected_story["status"] == "published" or is_creator()):
        st.markdown(f"## {selected_story['title']}")
        st.caption(selected_story["genre"])
        chapters = query("SELECT * FROM chapters WHERE story_id=? ORDER BY position", (sid,))
        chapter_ids = [x["id"] for x in chapters]
        if chapters:
            current_id = st.session_state.get("read_chapter", chapter_ids[0])
            current = next((x for x in chapters if x["id"] == current_id), chapters[0])
            st.subheader(current["title"])
            st.markdown(current["body"].replace("\n", "  \n"))
            ix = chapter_ids.index(current["id"])
            a,b = st.columns(2)
            with a:
                if ix > 0 and st.button("← Previous chapter"):
                    st.session_state.read_chapter = chapter_ids[ix-1]; st.rerun()
            with b:
                if ix < len(chapters)-1 and st.button("Next chapter →"):
                    st.session_state.read_chapter = chapter_ids[ix+1]; st.rerun()
            if u and u["role"] == "reader":
                execute("INSERT INTO progress(user_id,story_id,chapter_id,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id,story_id) DO UPDATE SET chapter_id=excluded.chapter_id,updated_at=excluded.updated_at",
                        (u["id"],sid,current["id"],datetime.now().isoformat()))
        if u and selected_story["comments_enabled"] and selected_story["status"] == "published":
            st.markdown("### Reader comments")
            with st.form("comment_form"):
                comment_text = st.text_area("Share a thoughtful comment", max_chars=1500)
                posted = st.form_submit_button("Post comment")
            if posted:
                if not u: st.error("Log in to comment.")
                elif comment_text.strip():
                    execute("INSERT INTO comments(body,created_at,story_id,user_id) VALUES(?,?,?,?)",
                            (comment_text.strip(),datetime.now().isoformat(),sid,u["id"]))
                    st.rerun()
            for cm in query("SELECT comments.*,users.username FROM comments JOIN users ON users.id=comments.user_id WHERE story_id=? ORDER BY comments.id DESC",(sid,)):
                st.markdown(f"**{cm['username']}** · {cm['created_at'][:10]}  \n{cm['body']}")
                if is_creator() and st.button("Remove comment",key=f"delcm_{cm['id']}"):
                    execute("DELETE FROM comments WHERE id=?",(cm["id"],)); st.rerun()
        if u and (selected_story["status"] == "published" or is_creator()):
            st.download_button("Export this story as PDF",pdf_bytes(selected_story),file_name=f"{selected_story['title']}.pdf",mime="application/pdf")
    else:
        st.warning("This story is not available.")
    if st.button("← Back to StoryVerse"):
        st.session_state.pop("open_story",None); st.rerun()
    st.stop()

if page == "Home":
    st.markdown("## A little corner for book lovers")
    st.write("Discover published stories, settle into a chapter, and keep your favourite reads close.")
    published = query("SELECT * FROM stories WHERE status='published' ORDER BY updated_at DESC LIMIT 12")
    if not published: st.info("No stories have been published yet. The first chapter is waiting to be written.")
    for s in published: story_tile(s)

elif page == "Search stories":
    st.markdown("## Find your next favourite")
    term = st.text_input("Search by title, description or genre")
    if term:
        like = f"%{term}%"
        found = query("SELECT * FROM stories WHERE status='published' AND (title LIKE ? OR description LIKE ? OR genre LIKE ?) ORDER BY updated_at DESC",(like,like,like))
    else:
        found = query("SELECT * FROM stories WHERE status='published' ORDER BY updated_at DESC")
    st.caption(f"{len(found)} stories found")
    for s in found: story_tile(s)

elif page == "My bookshelf":
    st.markdown("## My bookshelf")
    if not u: st.info("Log in to view your bookshelf.")
    else:
        saved = query("SELECT stories.* FROM stories JOIN bookmarks ON stories.id=bookmarks.story_id WHERE bookmarks.user_id=? AND stories.status='published' ORDER BY bookmarks.id DESC",(u["id"],))
        if not saved: st.info("Your bookshelf is empty. Save a story to find it here.")
        for s in saved: story_tile(s, False)
        st.markdown("### Continue reading")
        prog = query("SELECT stories.title, stories.id AS sid, chapters.id AS cid, chapters.title AS chapter_title FROM progress JOIN stories ON stories.id=progress.story_id LEFT JOIN chapters ON chapters.id=progress.chapter_id WHERE progress.user_id=?",(u["id"],))
        for p in prog:
            if st.button(f"{p['title']} — {p['chapter_title'] or 'Start reading'}",key=f"continue_{p['sid']}"):
                st.session_state.open_story=p["sid"]; st.session_state.read_chapter=p["cid"]; st.rerun()

elif page == "Writing goals":
    st.markdown("## Daily writing goal")
    if u:
        today = date.today().isoformat()
        goal = query("SELECT * FROM goals WHERE user_id=? AND goal_date=?",(u["id"],today),one=True)
        if not goal:
            execute("INSERT INTO goals(user_id,goal_date,target_words,words_written) VALUES(?,?,500,0)",(u["id"],today))
            goal = query("SELECT * FROM goals WHERE user_id=? AND goal_date=?",(u["id"],today),one=True)
        with st.form("goal"):
            target = st.number_input("Today's word target",min_value=1,max_value=100000,value=int(goal["target_words"]))
            save = st.form_submit_button("Save goal")
        if save:
            execute("UPDATE goals SET target_words=? WHERE id=?",(int(target),goal["id"])); st.success("Goal updated.")
        if is_creator():
            st.caption("Your total words across all chapters")
            st.metric("Words written",word_count())
        st.progress(min(1.0,goal["words_written"]/max(1,goal["target_words"])))
        st.caption(f"{goal['words_written']} / {goal['target_words']} words recorded today. Daily word tracking can be updated from the creator studio.")

elif page == "Creator studio" and is_creator():
    st.markdown("## Creator studio")
    stories = query("SELECT * FROM stories ORDER BY updated_at DESC")
    st.metric("Total stories",len(stories))
    st.metric("Words in chapters",word_count())
    st.markdown("### Create a story")
    with st.form("new_story"):
        title = st.text_input("Story title")
        desc = st.text_area("Description")
        genre = st.selectbox("Genre",["Fantasy","Romance","Mystery","Thriller","Science Fiction","Adventure","Historical Fiction","Literary Fiction","Poetry","Other"])
        cover_upload = st.file_uploader("Cover image (PNG/JPG/WEBP)",type=["png","jpg","jpeg","webp"])
        create = st.form_submit_button("Create story")
    if create:
        if not title.strip(): st.error("A title is required.")
        else:
            cover = save_upload(cover_upload,"cover") if cover_upload else ""
            execute("INSERT INTO stories(title,description,genre,cover,status,created_at,updated_at,author_id) VALUES(?,?,?,?,?,?,?,?)",
                    (title.strip(),desc,genre,cover,"draft",datetime.now().isoformat(),datetime.now().isoformat(),u["id"]))
            st.success("Draft created."); st.rerun()
    for s in stories:
        with st.expander(f"{s['title']} · {s['status'].upper()}"):
            with st.form(f"edit_story_{s['id']}"):
                nt = st.text_input("Title",s["title"])
                nd = st.text_area("Description",s["description"] or "")
                ng = st.selectbox("Genre",["Fantasy","Romance","Mystery","Thriller","Science Fiction","Adventure","Historical Fiction","Literary Fiction","Poetry","Other"],index=["Fantasy","Romance","Mystery","Thriller","Science Fiction","Adventure","Historical Fiction","Literary Fiction","Poetry","Other"].index(s["genre"]) if s["genre"] in ["Fantasy","Romance","Mystery","Thriller","Science Fiction","Adventure","Historical Fiction","Literary Fiction","Poetry","Other"] else 9)
                new_cover = st.file_uploader("Replace cover",type=["png","jpg","jpeg","webp"],key=f"cover_{s['id']}")
                comments_on = st.checkbox("Allow comments",value=bool(s["comments_enabled"]))
                saved = st.form_submit_button("Save story details")
            if saved:
                cover = save_upload(new_cover,"cover") if new_cover else s["cover"]
                execute("UPDATE stories SET title=?,description=?,genre=?,cover=?,comments_enabled=?,updated_at=? WHERE id=?",
                        (nt.strip(),nd,ng,cover,int(comments_on),datetime.now().isoformat(),s["id"]))
                st.success("Story updated."); st.rerun()
            chapters = query("SELECT * FROM chapters WHERE story_id=? ORDER BY position",(s["id"],))
            st.caption(f"{len(chapters)} chapter(s)")
            with st.form(f"new_chapter_{s['id']}"):
                ct = st.text_input("New chapter title")
                cb = st.text_area("Chapter text",height=260)
                add = st.form_submit_button("Save chapter draft")
            if add:
                if not ct.strip(): st.error("Chapter title is required.")
                else:
                    pos = (chapters[-1]["position"]+1) if chapters else 1
                    execute("INSERT INTO chapters(title,body,position,created_at,updated_at,story_id) VALUES(?,?,?,?,?,?)",
                            (ct.strip(),cb,pos,datetime.now().isoformat(),datetime.now().isoformat(),s["id"]))
                    st.success("Chapter saved."); st.rerun()
            for ch in chapters:
                with st.expander(f"Edit: {ch['title']}"):
                    with st.form(f"chapter_edit_{ch['id']}"):
                        et = st.text_input("Chapter title",ch["title"])
                        eb = st.text_area("Chapter text",ch["body"] or "",height=300)
                        ec = st.form_submit_button("Save chapter")
                    if ec:
                        execute("UPDATE chapters SET title=?,body=?,updated_at=? WHERE id=?",(et.strip(),eb,datetime.now().isoformat(),ch["id"]))
                        st.success("Chapter updated."); st.rerun()
            st.write("**Publishing controls**")
            a,b,c = st.columns(3)
            with a:
                if st.button("Publish",key=f"pub_{s['id']}"):
                    if not chapters: st.error("Add at least one chapter before publishing.")
                    else: execute("UPDATE stories SET status='published',updated_at=? WHERE id=?",(datetime.now().isoformat(),s["id"])); st.rerun()
            with b:
                if st.button("Unpublish",key=f"unpub_{s['id']}"):
                    execute("UPDATE stories SET status='unpublished',updated_at=? WHERE id=?",(datetime.now().isoformat(),s["id"])); st.rerun()
            with c:
                if st.button("Return to draft",key=f"draft_{s['id']}"):
                    execute("UPDATE stories SET status='draft',updated_at=? WHERE id=?",(datetime.now().isoformat(),s["id"])); st.rerun()
            if st.button("Delete story",key=f"delete_{s['id']}"):
                execute("DELETE FROM stories WHERE id=?",(s["id"],)); st.rerun()
            if chapters:
                st.download_button("Export story PDF",pdf_bytes(s),file_name=f"{s['title']}.pdf",mime="application/pdf",key=f"pdf_{s['id']}")

elif page == "Background & appearance" and is_creator():
    st.markdown("## Background & appearance")
    st.write("The default look is a midnight-blue star field. Upload a background image whenever you want.")
    upload = st.file_uploader("Upload a new background image",type=["png","jpg","jpeg","webp"])
    if st.button("Apply uploaded background",disabled=upload is None):
        path = save_upload(upload,"background")
        if path:
            execute("INSERT INTO settings(key,value) VALUES('background',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(path,))
            st.success("Background updated."); st.rerun()
    if st.button("Restore the default starry blue background"):
        execute("DELETE FROM settings WHERE key='background'")
        st.success("Default background restored."); st.rerun()

st.markdown("<div style='text-align:center;color:#9eabc8;padding:2rem 0 1rem;font-size:.85rem'>✦ StoryVerse · A quiet place for stories ✦</div>",unsafe_allow_html=True)
