"""Unit tests. Run: python3 -m unittest discover -s scripts/tests -q   (no network needed)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
_TMP = tempfile.mkdtemp(prefix="leadgen-test-")
os.environ["LEADGEN_DATA_DIR"] = _TMP  # must be set before importing leadgen.config

from leadgen import util, db, config, crawl, score, export  # noqa: E402
from leadgen.sources import osm, places, csv_import, base_record  # noqa: E402
from leadgen.contacts import pattern  # noqa: E402
from leadgen.connectors import instantly, ghl  # noqa: E402
from leadgen import cli  # noqa: E402


def icp():
    return config.load_icp(config.ICP_EXAMPLE)


class TestUtil(unittest.TestCase):
    def test_normalize_website(self):
        self.assertEqual(util.normalize_website("www.Joes-Dental.com/about/"), ("https://joes-dental.com/about", "joes-dental.com", "site"))
        self.assertEqual(util.normalize_website("http://example.org")[1], "example.org")
        self.assertEqual(util.normalize_website("https://www.facebook.com/joes")[2], "social")
        self.assertEqual(util.normalize_website("https://g.page/joes")[2], "non_company")
        self.assertEqual(util.normalize_website(""), ("", "", ""))
        self.assertEqual(util.normalize_website("not a url"), ("", "", ""))
        self.assertEqual(util.normalize_website("mailto:x@y.com")[2], "")
        self.assertTrue(util.is_site_builder_domain("joes.wixsite.com"))

    def test_normalize_phone(self):
        self.assertEqual(util.normalize_phone("(512) 555-0199"), "+15125550199")
        self.assertEqual(util.normalize_phone("1-512-555-0199"), "+15125550199")
        self.assertEqual(util.normalize_phone("+44 20 7946 0958"), "+442079460958")
        self.assertEqual(util.normalize_phone("020 7946 0958", "GB"), "+442079460958")
        self.assertEqual(util.normalize_phone("123"), "")

    def test_clean_email(self):
        self.assertEqual(util.clean_email("Mailto:Info@Joes-Dental.com?subject=hi"), "info@joes-dental.com")
        self.assertEqual(util.clean_email("you@example.com"), "")
        self.assertEqual(util.clean_email("logo@2x.png"), "")
        self.assertEqual(util.clean_email("abc@sentry.wixpress.com"), "")
        self.assertEqual(util.clean_email("(dr.kim@rrfamilydental.com)."), "dr.kim@rrfamilydental.com")
        self.assertEqual(util.clean_email("bad@@x.com"), "")
        self.assertEqual(util.clean_email("242-7455info@orthoinstitute.com"), "info@orthoinstitute.com")
        self.assertEqual(util.clean_email("1.512.555.0199dr.kim@joes.com"), "dr.kim@joes.com")
        self.assertEqual(util.clean_email("123dental@joes.com"), "123dental@joes.com")
        self.assertEqual(util.clean_email("example@smilegeneration.com"), "")
        self.assertEqual(util.clean_email("nombre@dominio.com"), "")

    def test_classify_email(self):
        self.assertEqual(util.classify_email("info@joes.com", "joes.com"), "role")
        self.assertEqual(util.classify_email("frontdesk@joes.com", "joes.com"), "role")
        self.assertEqual(util.classify_email("mary@joes.com", "joes.com"), "personal")
        self.assertEqual(util.classify_email("mary@gmail.com", "joes.com"), "personal_webmail")
        self.assertEqual(util.classify_email("dev@webagency.com", "joes.com"), "third_party")
        self.assertEqual(util.classify_email("mary@joesdental.net", "joesdental.com"), "personal")
        self.assertEqual(util.classify_email("info@weomedia.com", "soladentalaustin.com", "Sola Smile Co."), "third_party")
        self.assertEqual(util.classify_email("patients@solasmileaustin.com", "soladentalaustin.com", "Sola Smile Co."), "role")
        self.assertEqual(util.classify_email("ibrahim@celebratedental.com", "celebratedentalaustin.com"), "personal")
        self.assertEqual(util.classify_email("blvd5thstreet@mb2dental.com", "blvddentistry.com", "Blvd Dentistry"), "third_party")
        self.assertEqual(util.classify_email("info.joes@gmail.com", "joes.com"), "role")
        self.assertEqual(util.classify_email("front@secure.joesdental.com", "joesdental.com"), "role")

    def test_dedup_key(self):
        self.assertEqual(util.dedup_key("a.com", "", "X", ""), "d:a.com")
        self.assertEqual(util.dedup_key("", "+1555", "X", ""), "p:+1555")
        self.assertEqual(util.dedup_key("", "", "The Joe's Dental, LLC", "Austin"), "n:joe-s-dental|austin")

    def test_dotenv(self):
        p = os.path.join(_TMP, ".envtest")
        with open(p, "w") as fh:
            fh.write("# c\nexport A_TEST_KEY='v1'\nB_TEST_KEY=v2\nEMPTY=\n")
        os.environ.pop("A_TEST_KEY", None)
        n = util.load_dotenv(p)
        self.assertEqual(os.environ["A_TEST_KEY"], "v1")
        self.assertEqual(n, 2)


class TestDb(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(_TMP, "t_db.db"))
        self.conn.execute("DELETE FROM contacts"); self.conn.execute("DELETE FROM companies"); self.conn.execute("DELETE FROM suppression")

    def test_company_merge(self):
        i, new = db.upsert_company(self.conn, {"name": "Joes Dental", "domain": "joes.com", "website": "https://joes.com", "city": "Austin"}, "osm")
        j, new2 = db.upsert_company(self.conn, {"name": "Joe's Dental LLC", "domain": "joes.com", "phone": "+15125550199", "rating": 4.5}, "places")
        self.assertTrue(new); self.assertFalse(new2); self.assertEqual(i, j)
        c = db.get_company(self.conn, i)
        self.assertEqual(c["phone"], "+15125550199"); self.assertEqual(c["name"], "Joes Dental")
        self.assertEqual(json.loads(c["sources"]), ["osm", "places"])
        k, new3 = db.upsert_company(self.conn, {"name": "Joes Dental", "city": "Austin"}, "csv")  # no domain: same name + city
        self.assertFalse(new3); self.assertEqual(k, i)
        p1, _ = db.upsert_company(self.conn, {"name": "Rio Plumbing", "phone": "+15125550111", "city": "Austin"}, "osm")
        p2, new5 = db.upsert_company(self.conn, {"name": "Rio Plumbing & Drain", "domain": "rioplumbing.com", "phone": "+15125550111"}, "places")
        self.assertFalse(new5); self.assertEqual(p1, p2)  # the phone joins the OSM row and the Places row
        o, new6 = db.upsert_company(self.conn, {"name": "Joes Dental", "domain": "otherjoes.com", "city": "Austin"}, "csv")
        self.assertTrue(new6)  # same name, different website: a different business
        with self.assertRaises(ValueError):
            db.upsert_company(self.conn, {"name": ""}, "x")

    def test_contact_merge_and_suppress(self):
        i, _ = db.upsert_company(self.conn, {"name": "Joes", "domain": "joes.com"}, "osm")
        a, new = db.upsert_contact(self.conn, i, {"email": "mary@joes.com", "email_confidence": 60, "email_type": "personal"})
        b, new2 = db.upsert_contact(self.conn, i, {"email": "mary@joes.com", "email_confidence": 90, "title": "Owner", "verify_status": "valid"})
        self.assertEqual(a, b); self.assertFalse(new2)
        row = self.conn.execute("SELECT * FROM contacts WHERE id = ?", (a,)).fetchone()
        self.assertEqual(row["email_confidence"], 90); self.assertEqual(row["title"], "Owner"); self.assertEqual(row["verify_status"], "valid")
        c, new3 = db.upsert_contact(self.conn, i, {"first_name": "Bob", "last_name": "Ray"})
        d, new4 = db.upsert_contact(self.conn, i, {"first_name": "bob", "last_name": "RAY", "email": "bob@joes.com"})
        self.assertEqual(c, d); self.assertFalse(new4)
        self.assertTrue(db.suppress(self.conn, "email", "Mary@joes.com", "asked"))
        self.assertEqual(self.conn.execute("SELECT status FROM contacts WHERE id = ?", (a,)).fetchone()[0], "do_not_contact")
        emails, domains = db.suppression_sets(self.conn)
        self.assertIn("mary@joes.com", emails)


def _cfemail(email: str, key: int = 0x24) -> str:
    return "%02x" % key + "".join("%02x" % (ord(ch) ^ key) for ch in email)


class TestCrawl(unittest.TestCase):
    HTML = ('<html><head><title>Joe&#39;s Dental | Austin</title><meta name="description" content="Family dentist">'
            '<meta name="viewport" content="w"></head><body><a href="/contact-us">Contact</a><a href="/about">About Us</a>'
            '<a href="/blog">Blog</a><a href="https://www.facebook.com/joesdental">fb</a><a href="https://other.com/team">x</a>'
            '<a href="mailto:Info@JoesDental.com?subject=x">email</a><a href="tel:(512) 555-0199">call</a>'
            '<span class="__cf_email__" data-cfemail="' + _cfemail("dr.kim@joesdental.com") + '">[email]</span>'
            '<p>Dr. Mary at mary [at] joesdental [dot] com</p><img src="logo@2x.png"><script src="https://assets.calendly.com/x.js"></script>'
            '<footer>&copy; 2021 Joe\'s</footer></body></html>')

    def test_extract(self):
        ex = crawl._Extractor(); ex.feed(self.HTML)
        emails = crawl.extract_emails(self.HTML, ex)
        self.assertEqual(emails, {"info@joesdental.com", "dr.kim@joesdental.com", "mary@joesdental.com"})
        self.assertEqual(crawl.pick_pages("https://joesdental.com/", ex.links, 5),
                         ["https://joesdental.com/contact-us", "https://joesdental.com/about"])
        sig = crawl.detect_signals(self.HTML, "https://joesdental.com/", ex, 1, True)
        self.assertTrue(sig["booking_widget"]); self.assertTrue(sig["site_stale"]); self.assertEqual(sig["copyright_year"], 2021)
        self.assertTrue(sig["mobile_viewport"]); self.assertNotIn("chat_widget", sig)
        self.assertEqual(ex.tels, {"(512) 555-0199"})

    def test_extract_skips_page_noise(self):
        html = ('<html><!-- // www.weomedia.com | info@weomedia.com --><body>'
                '<input type="email" placeholder="hello@smilegeneration.com" name="email">'
                '<script>var d = {"html":"\\n\\t\\triverside@aloha-dental.com\\n","alt":"desk\\u0040aloha-dental.com"};</script>'
                '<p>Orthodontic Teaching Institute (737) 242-7455info@ortho-ti.com Office Hours</p></body></html>')
        ex = crawl._Extractor(); ex.feed(html)
        self.assertEqual(crawl.extract_emails(html, ex), {"riverside@aloha-dental.com", "desk@aloha-dental.com", "info@ortho-ti.com"})

    def test_decode_cfemail(self):
        self.assertEqual(crawl.decode_cfemail(_cfemail("a@b.co", 0x5a)), "a@b.co")


class TestPattern(unittest.TestCase):
    def test_infer_apply(self):
        self.assertEqual(pattern.infer([{"email": "mary.smith@x.com", "first_name": "Mary", "last_name": "Smith"},
                                        {"email": "bob.ray@x.com", "first_name": "Bob", "last_name": "Ray"}]), "{first}.{last}")
        self.assertEqual(pattern.apply("{f}{last}", "Mary", "O'Smith"), "mosmith")
        self.assertEqual(pattern.apply("{first}", "", ""), "")
        self.assertIsNone(pattern.infer([{"email": "zzz@x.com", "first_name": "A", "last_name": "B"}]))


class TestScore(unittest.TestCase):
    def company(self, **kw):
        base = {"id": 1, "name": "Joes Dental", "website": "https://joes.com", "domain": "joes.com", "phone": "+1", "category": "dentist",
                "signals": "{}", "crawl_status": "ok", "rating": None, "review_count": None, "description": "", "industry": "", "tags": "", "employees": None}
        base.update(kw); return base

    def test_qualify_and_primary(self):
        cs = [{"id": 1, "email": "info@joes.com", "email_type": "role", "verify_status": "unknown", "verify_detail": "mx_ok", "email_source": "crawl", "email_confidence": 80, "status": "new"},
              {"id": 2, "email": "mary@joes.com", "email_type": "personal", "verify_status": "unverified", "email_source": "crawl", "email_confidence": 85, "status": "new", "title": "Practice Manager"}]
        s, reasons, q, prim = score.score_company(self.company(), cs, icp())
        self.assertTrue(q); self.assertEqual(prim, 2); self.assertGreaterEqual(s, 70)
        self.assertTrue(any("no_booking_widget" in r for r in reasons))

    def test_disqualify(self):
        s, reasons, q, prim = score.score_company(self.company(name="Dental Supply Co"), [], icp())
        self.assertFalse(q); self.assertTrue(reasons[0].startswith("DISQUALIFIED")); self.assertIn("supply", reasons[0])
        s, reasons, q, prim = score.score_company(self.company(website="", domain=""), [], icp())
        self.assertIn("no website", reasons[0])
        s, reasons, q, prim = score.score_company(self.company(employees="120"), [], icp())
        self.assertIn("employees 120 > 50", reasons[0])
        s, reasons, q, prim = score.score_company(self.company(), [], icp(), suppressed_domains={"joes.com"})
        self.assertIn("suppressed", reasons[0])

    def test_offsite_crawl_email_not_used(self):
        cs = [{"id": 1, "email": "website@agency.com", "email_type": "third_party", "verify_status": "unknown", "verify_detail": "mx_ok", "email_source": "crawl", "email_confidence": 25, "status": "new"}]
        s, reasons, q, prim = score.score_company(self.company(), cs, icp())
        self.assertIsNone(prim); self.assertTrue(any("no usable email" in r for r in reasons))
        cs[0]["email_source"] = "apollo"
        s, reasons, q, prim = score.score_company(self.company(), cs, icp())
        self.assertEqual(prim, 1); self.assertTrue(any("only third-party" in r for r in reasons))

    def test_invalid_email_not_used(self):
        cs = [{"id": 1, "email": "x@joes.com", "email_type": "personal", "verify_status": "invalid", "email_source": "crawl", "email_confidence": 80, "status": "new"}]
        s, reasons, q, prim = score.score_company(self.company(), cs, icp())
        self.assertIsNone(prim); self.assertTrue(any("no usable email" in r for r in reasons))


class TestSourcesPure(unittest.TestCase):
    def test_osm(self):
        q = osm.build_query(osm.PRESETS["yoga"], (30.1, -97.9, 30.5, -97.6))
        self.assertIn('nwr["leisure"="fitness_centre"]["sport"="yoga"]["name"](30.1,-97.9,30.5,-97.6);', q)
        self.assertIn('["shop"~"beauty|hairdresser",i]', osm._filter_clause("shop~beauty|hairdresser"))
        self.assertIn('["name"~"barber",i]', osm._filter_clause("shop=hairdresser;name~(?i)barber"))  # Overpass rejects inline (?i)
        el = {"type": "node", "id": 5, "lat": 30.5, "lon": -97.7, "tags": {"name": "Joe's Dental", "website": "joesdental.com", "phone": "+1 512-555-0199",
              "addr:city": "Round Rock", "addr:state": "TX", "email": "info@joesdental.com", "contact:facebook": "https://facebook.com/joes"}}
        r = osm.element_to_record(el, "dentist", "US")
        self.assertEqual(r["domain"], "joesdental.com"); self.assertEqual(r["phone"], "+15125550199"); self.assertEqual(r["_email"], "info@joesdental.com")
        self.assertEqual(r["source_ref"], "osm:node/5"); self.assertEqual(r["category"], "dentist")
        self.assertIsNone(osm.element_to_record({"type": "node", "id": 1, "tags": {"amenity": "dentist"}}, "dentist", "US"))

    def test_places(self):
        cells = places.grid_cells(30.27, -97.74, 10, 4)
        self.assertTrue(20 <= len(cells) <= 40)
        p = {"id": "abc", "displayName": {"text": "Joe's Dental"}, "formattedAddress": "1 Main St, Austin, TX 78701, USA",
             "addressComponents": [{"types": ["locality"], "longText": "Austin"}, {"types": ["administrative_area_level_1"], "shortText": "TX"},
                                   {"types": ["postal_code"], "longText": "78701"}, {"types": ["country"], "shortText": "US"}],
             "websiteUri": "http://www.joesdental.com/", "nationalPhoneNumber": "(512) 555-0199", "rating": 4.7, "userRatingCount": 88,
             "primaryType": "dentist", "businessStatus": "OPERATIONAL", "location": {"latitude": 30.2, "longitude": -97.7}}
        r = places.place_to_record(p, "dentist", "US")
        self.assertEqual((r["city"], r["state"], r["postal_code"], r["domain"], r["rating"]), ("Austin", "TX", "78701", "joesdental.com", 4.7))
        p["businessStatus"] = "CLOSED_PERMANENTLY"
        self.assertIsNone(places.place_to_record(p, "dentist", "US"))

    def test_base_record_social_as_website(self):
        r = base_record("X", "https://www.facebook.com/x", "", "US")
        self.assertNotIn("website", r); self.assertEqual(r["facebook_url"], "https://www.facebook.com/x")

    def test_csv_automap(self):
        m = csv_import.auto_map(["Business Name", "Website", "Phone", "Email", "City", "First Name"], {})
        self.assertEqual(m["name"], "Business Name"); self.assertEqual(m["first_name"], "First Name")
        with self.assertRaises(SystemExit):
            csv_import.auto_map(["Business Name"], {"name": "Nope"})


class TestExportConnectors(unittest.TestCase):
    ROW = {"lead_id": "1-2", "company_id": 1, "contact_id": 2, "company_name": "Joes Dental", "website": "https://joesdental.com",
           "domain": "joesdental.com", "email": "mary@joesdental.com", "first_name": "Mary", "last_name": "Smith", "title": "Practice Manager",
           "contact_phone": "", "company_phone": "+15125550199", "city": "Austin", "state": "TX", "country": "US", "category": "dentist",
           "rating": 4.8, "review_count": 40, "verify_status": "unknown", "email_type": "personal", "score": 75, "signals": "chat_widget",
           "source": "osm", "address": "1 Main St", "postal_code": "78701", "campaign": "austin-dentists", "description": "", "google_maps_url": "",
           "score_reasons": "+10 x", "linkedin_url": "", "facebook_url": "", "instagram_url": "", "email_source": "crawl", "email_confidence": 85,
           "verify_detail": "mx_ok", "full_name": "Mary Smith", "seniority": "", "industry": "", "employees": "", "source_ref": "", "tags": "", "is_primary": 1}

    def test_formats(self):
        for fmt, conv in export.FORMATS.items():
            out = conv(self.ROW)
            self.assertIn("mary@joesdental.com", out.values(), fmt)
        self.assertEqual(export.FORMATS["ghl"](self.ROW)["Tags"], "lead-gen-employee,austin-dentists,dentist")

    def test_instantly_lead(self):
        lead = instantly.build_lead(self.ROW)
        self.assertEqual(lead["email"], "mary@joesdental.com"); self.assertEqual(lead["job_title"], "Practice Manager")
        self.assertEqual(lead["custom_variables"]["city"], "Austin"); self.assertNotIn("first_name", instantly.build_lead({**self.ROW, "first_name": ""}))
        for v in lead["custom_variables"].values():
            self.assertIsInstance(v, (str, int, float, bool))

    def test_ghl_contact(self):
        body = ghl.build_contact(self.ROW, "LOC1", ["a"])
        self.assertEqual(body["locationId"], "LOC1"); self.assertEqual(body["firstName"], "Mary"); self.assertEqual(body["postalCode"], "78701")
        body2 = ghl.build_contact({**self.ROW, "first_name": "", "last_name": ""}, "LOC1", [])
        self.assertEqual(body2["name"], "Joes Dental")
        self.assertEqual(ghl.headers("t")["Version"], os.environ.get("GHL_API_VERSION", "2021-07-28"))
        self.assertEqual(ghl.row_tags({"campaign": "austin-dentists", "category": "dentist"}, ["x", "dentist"]),
                         ["x", "dentist", "austin-dentists"])  # preview and live push use the same tags

    def test_validate_icp(self):
        ex = icp()
        self.assertTrue(any("example name" in p for p in config.validate_icp(ex)))  # an unedited example never runs
        ex["campaign"] = "austin-dentists"
        self.assertEqual(config.validate_icp(ex), [])
        ex["signals"]["bonus"]["no_chatt_widget"] = 5
        self.assertTrue(any("no_chatt_widget" in p for p in config.validate_icp(ex)))


class TestCliPipeline(unittest.TestCase):
    """CSV import -> local verify (DNS may be unavailable; tolerated) -> score -> export, through the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.data = os.path.join(_TMP, "clidata")
        os.makedirs(cls.data, exist_ok=True)
        config.DATA_DIR = cls.data
        config.DB_PATH = os.path.join(cls.data, "leadgen.db")
        config.EXPORT_DIR = os.path.join(cls.data, "exports")
        config.ICP_PATH = config.ICP_EXAMPLE

    def run_cli(self, *argv):
        return cli.main(list(argv))

    def test_pipeline(self):
        sample = os.path.join(ROOT, "data", "samples", "companies_sample.csv")
        self.run_cli("source", "csv", sample)
        conn = db.connect(config.DB_PATH)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 5)
        fb = conn.execute("SELECT website, facebook_url FROM companies WHERE name = 'Lakeway Dental Care'").fetchone()
        self.assertIsNone(fb["website"]); self.assertTrue(fb["facebook_url"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 4)
        # scoring without network verification
        self.run_cli("score")
        rows = conn.execute("SELECT name, qualified, score_reasons FROM companies").fetchall()
        byname = {r["name"]: r for r in rows}
        self.assertEqual(byname["Dental Supply Depot"]["qualified"], 0)
        self.assertEqual(byname["Lakeway Dental Care"]["qualified"], 0)  # require_website
        self.assertEqual(byname["Round Rock Family Dentistry"]["qualified"], 1)
        self.run_cli("suppress", "add", "--email", "info@brightsmiledental-example.com")
        out = os.path.join(self.data, "out.csv")
        self.run_cli("export", "--format", "generic", "--out", out)
        with open(out) as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0].split(",")[0], "lead_id")
        emails = [l.split(",")[6] for l in lines[1:]]
        self.assertIn("dr.kim@rrfamilydental-example.com", emails)
        self.assertNotIn("info@brightsmiledental-example.com", emails)
        self.assertNotIn("sales@dentalsupply-example.com", emails)
        # dry-run push with a list target does not need network or a key beyond presence
        os.environ["INSTANTLY_API_KEY"] = "test-key"
        rc = self.run_cli("push", "instantly", "--list", "Test List")
        self.assertEqual(rc, 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM contacts WHERE status = 'pushed'").fetchone()[0], 0)
        self.run_cli("add", "--name", "Manual Dental", "--website", "manualdental-example.com", "--city", "Austin", "--ref", "https://example.org/list")
        self.assertEqual(conn.execute("SELECT source FROM companies WHERE name = 'Manual Dental'").fetchone()[0], "web_research")
        self.assertEqual(self.run_cli("sql", "DELETE FROM companies"), 2)  # refused without --write
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 6)
        self.run_cli("status")
        self.run_cli("missing", "--field", "email")

    def test_report(self):
        from leadgen import report
        conn = db.connect(os.path.join(self.data, "report.db"))
        self.assertIn('id="leadgen-data"', report.build(conn, icp(), config.EXPORT_DIR))  # an empty store still renders
        cid, _ = db.upsert_company(conn, {"name": "Evil </script><img src=x> Dental", "website": "https://evil-example.com",
                                          "city": "Austin", "lat": 30.27, "lng": -97.74}, "csv")
        db.upsert_contact(conn, cid, {"email": "info@evil-example.com", "email_type": "role", "verify_status": "invalid"})
        conn.commit()
        out = os.path.join(self.data, "report.html")
        with open(report.write(conn, icp(), config.EXPORT_DIR, out), encoding="utf-8") as fh:
            html_text = fh.read()
        self.assertIn("<title>", html_text)
        self.assertIn('id="leads"', html_text)
        self.assertNotIn("</script><img", html_text)  # scraped text cannot break out of the data block
        data = json.loads(html_text.split('id="leadgen-data">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(data["leads"][0]["name"], "Evil </script><img src=x> Dental")
        self.assertEqual(data["leads"][0]["people"][0]["blocked"], "invalid")
        self.assertEqual(data["kpi"]["ready"], 0)
        self.assertEqual(self.run_cli("report", "--out", out), 0)
        # hand-edited or odd rows never break the page: no Infinity in the JSON, wrong-shaped JSON columns ignored
        bad, _ = db.upsert_company(conn, {"name": "Odd Co", "rating": float("inf"), "city": "Austin"}, "csv")
        db.update_company(conn, bad, signals="[]", sources='"osm"', name="")
        conn.commit()
        data = json.loads(report.build(conn, icp(), config.EXPORT_DIR).split('id="leadgen-data">', 1)[1].split("</script>", 1)[0])
        odd = [l for l in data["leads"] if l["id"] == bad][0]
        self.assertIsNone(odd.get("rating"))
        self.assertEqual(odd["name"], "Unnamed company")
        self.assertEqual(util.parse_json('"osm"', []), [])

    def test_suppression_sticks(self):
        conn = db.connect(os.path.join(self.data, "supp.db"))
        cid, _ = db.upsert_company(conn, {"name": "Agency Only", "domain": "agencyonly-example.com", "city": "Austin"}, "csv")
        db.suppress(conn, "email", "owner@agencyonly-example.com", "asked")
        k, _ = db.upsert_contact(conn, cid, {"email": "owner@agencyonly-example.com", "email_type": "personal"})
        self.assertEqual(conn.execute("SELECT status FROM contacts WHERE id = ?", (k,)).fetchone()[0], "do_not_contact")
        db.upsert_contact(conn, cid, {"email": "hi@webagency-example.com", "email_type": "third_party", "email_source": "crawl"})
        conn.execute("UPDATE companies SET qualified = 1")
        conn.commit()
        self.assertEqual(cli.status_data(conn, icp())["ready_leads"], 0)  # neither address can export, so not ready


if __name__ == "__main__":
    unittest.main()
