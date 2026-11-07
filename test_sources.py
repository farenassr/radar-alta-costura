from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import sources


NOW = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)


class SourcesTest(unittest.TestCase):
    def test_secop_checks_phase_and_bidding_deadline(self):
        process = {
            "id_del_proceso": "CO1.REQ.1",
            "nombre_del_procedimiento": "Diseño de vestuario escénico",
            "descripci_n_del_procedimiento": "Patronaje y confección a medida",
            "fecha_de_recepcion_de": "2026-11-07T09:00:00.000",
            "estado_del_procedimiento": "Publicado",
            "estado_de_apertura_del_proceso": "Abierto",
            "estado_resumen": "Presentación de oferta",
            "adjudicado": "No",
            "entidad": "Teatro",
            "ciudad_entidad": "Bogotá",
            "precio_base": "7200000",
            "urlproceso": {"url": "https://community.secop.gov.co/call?id=1"},
        }
        rows = [
            process,
            dict(process, id_del_proceso="2", estado_resumen="Presentación de observaciones"),
            dict(process, id_del_proceso="3", estado_del_procedimiento="Cancelado"),
            dict(process, id_del_proceso="4", fecha_de_recepcion_de="2026-11-06T19:00:00.000"),
            dict(process, id_del_proceso="5", nombre_del_procedimiento="Compra de uniformes"),
            dict(process, id_del_proceso="6", estado_de_apertura_del_proceso="Cerrado"),
            dict(process, id_del_proceso="7", nombre_del_procedimiento="Dotaciones de vestuario y calzado"),
        ]
        with patch.object(sources, "fetch_json", return_value=rows):
            result = sources.secop(NOW)
        self.assertEqual([row["id"] for row in result], ["secop:CO1.REQ.1"])
        self.assertEqual(result[0]["deadline"], "2026-11-07T09:00:00-05:00")
        self.assertIn("7.200.000", result[0]["compensation"])

    def test_inexmoda_needs_explicit_deadline_and_application(self):
        post = {
            "id": 10,
            "title": {"rendered": "Convocatoria abierta para diseñadoras"},
            "date_gmt": "2026-11-01T12:00:00",
            "link": "https://inexmoda.org.co/convocatoria/",
        }
        link = '<a href="https://forms.example.org/inscripcion">Postúlate aquí</a>'
        rows = [
            dict(post, content={"rendered": "<p>Inscripciones hasta el 30 de noviembre de 2026.</p>" + link}),
            dict(post, id=11, content={"rendered": "<p>Inscripciones hasta el 30 de noviembre.</p>" + link}),
            dict(post, id=12, content={"rendered": "<p>Inscripciones hasta el 30 de noviembre de 2026.</p>"}),
            dict(post, id=13, content={"rendered": "<p>Convocatoria cerrada.</p><p>Cierre: 30 de noviembre de 2026.</p>" + link}),
            dict(post, id=14, content={"rendered": "<p>Inscripciones hasta el 30 de noviembre de 2025.</p>" + link}),
        ]
        with patch.object(sources, "fetch_json", return_value=rows):
            result = sources.inexmoda(NOW)
        self.assertEqual([row["id"] for row in result], ["inexmoda:10"])
        self.assertEqual(result[0]["url"], "https://forms.example.org/inscripcion")

    def test_himalayas_checks_both_restrictions_and_expiry(self):
        guid = "https://himalayas.app/companies/studio/jobs/patternmaker"
        job = {
            "guid": guid,
            "title": "Patternmaker",
            "companyName": "Studio",
            "applicationLink": guid + "?utm_source=api",
            "expiryDate": NOW.timestamp() + 3600,
            "pubDate": NOW.timestamp() - 3600,
            "locationRestrictions": [{"alpha2": "CO", "name": "Colombia"}],
            "timezoneRestrictions": [-6, -5],
        }
        jobs = [
            job,
            dict(job, guid=guid + "-colombia", locationRestrictions=["United States", "Colombia"]),
            dict(job, guid=guid + "-west", timezoneRestrictions=["UTC-8"]),
            dict(job, guid=guid + "-us", locationRestrictions=["United States"]),
            dict(job, guid=guid + "-past", expiryDate=NOW.timestamp()),
            dict(job, guid=guid + "-unknown-country", locationRestrictions=None),
            dict(job, guid=guid + "-unknown-timezone", timezoneRestrictions=None),
        ]
        with patch.object(sources, "fetch_json", return_value={"jobs": jobs}):
            result = sources.himalayas(NOW)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["section"], "colombia")
        self.assertEqual(result[0]["sourceUrl"], guid)
        self.assertEqual(result[0]["url"], guid + "?utm_source=api")

    def test_reformation_filters_store_and_evergreen_posts(self):
        job = {
            "id": 1,
            "internal_job_id": 12,
            "title": "Senior Technical Designer",
            "absolute_url": "https://job-boards.greenhouse.io/reformation/jobs/1",
            "location": {"name": "Vernon, CA"},
            "content": "&lt;p&gt;Develop garment patterns. The base salary range is $100,000 – $120,000.&lt;/p&gt;",
        }
        jobs = [
            job,
            dict(job, id=2, title="General Design Application", internal_job_id=None),
            dict(job, id=3, title="Store Associate"),
            dict(job, id=4, application_deadline="2026-11-06T12:00:00-05:00"),
            dict(job, id=5, title="Temporary Operations Associate, Part Time - Design District"),
        ]
        with patch.object(sources, "fetch_json", side_effect=[{"jobs": jobs}, job]):
            result = sources.reformation(NOW)
        self.assertEqual([row["id"] for row in result], ["reformation:1"])
        self.assertEqual(result[0]["location"], "Vernon, CA")
        self.assertIn("Develop garment patterns", result[0]["description"])
        self.assertEqual(result[0]["compensation"], "$100,000–$120,000")

    def test_mulberry_includes_active_ready_to_wear_with_explicit_workplace(self):
        job = {
            "id": "job-one", "text": "Junior RTW Designer",
            "categories": {"team": "Ready-to-Wear", "location": "London"},
            "workplaceType": "hybrid", "createdAt": NOW.timestamp() * 1000,
            "applyUrl": "https://jobs.lever.co/mulberry/job-one/apply",
            "hostedUrl": "https://jobs.lever.co/mulberry/job-one",
            "description": "<p>Develop seasonal garment collections</p>",
        }
        jobs = [job, dict(job, id="job-two", workplaceType="remote"),
                dict(job, id="job-three", categories={"team": "Retail", "location": "London"})]
        with patch.object(sources, "fetch_json", return_value=jobs):
            result = sources.mulberry(NOW)
        self.assertEqual([row["id"] for row in result], ["mulberry:job-one"])
        self.assertEqual(result[0]["modality"], "hibrido")
        self.assertEqual(result[0]["section"], "internacional")
        self.assertEqual(result[0]["url"], job["applyUrl"])


if __name__ == "__main__":
    unittest.main()
