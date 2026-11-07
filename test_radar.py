import unittest
from datetime import datetime, timedelta, timezone

from radar import collect, rank


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def opportunity(id="test:1", **changes):
    return {
        "id": id, "title": "Haute couture patternmaker", "organization": "Atelier Uno",
        "type": "empleo", "modality": "remoto", "location": "Colombia",
        "section": "colombia", "deadline": None,
        "publishedAt": "2026-11-02T00:00:00Z", "compensation": None,
        "url": "https://example.org/jobs/1", "sourceUrl": None,
        "clearApplication": True, "description": "", **changes,
    }


def source(callback, name="Fuente"):
    return name, "https://example.org", callback


class RankingTest(unittest.TestCase):
    def test_colombia_eligibility_is_worth_25_points(self):
        local = rank(opportunity(), NOW)
        abroad = rank(opportunity(section="internacional", modality="presencial"), NOW)
        self.assertEqual(local["score"], 100)
        self.assertEqual(local["score"] - abroad["score"], 25)

    def test_couture_beats_related_fashion_with_same_conditions(self):
        related = rank(opportunity(title="Patronista", description="Diseño de colección de moda"), NOW)
        direct = rank(opportunity(title="Première main haute couture"), NOW)
        self.assertGreater(direct["score"], related["score"])

    def test_business_roles_can_score_as_high_as_workshop_roles(self):
        strategy = rank(opportunity(title="Consultoría de estrategia para alta costura"), NOW)
        workshop = rank(opportunity(title="Patronista de alta costura"), NOW)
        self.assertEqual(strategy["score"], workshop["score"])

    def test_reject_irrelevant_expired_and_fees(self):
        cases = [
            {"title": "Sales associate, Design District", "description": "Luxury fashion"},
            {"title": "Compra de uniformes", "description": "Confección a medida"},
            {"title": "Développeur logiciel", "description": "A client interested in haute couture"},
            {"deadline": "2026-11-06T23:59:59Z"},
            {"description": "Debes pagar una cuota de inscripción"},
            {"description": "La inscripción tiene un costo de $50.000"},
            {"description": "Se requiere una cuota de inscripción de COP 30.000"},
            {"description": "The application fee is $50"},
            {"description": "Pay a $20 application fee"},
            {"url": "javascript:alert(1)"},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertIsNone(rank(opportunity(**case), NOW))

    def test_public_output_omits_raw_description(self):
        self.assertNotIn("description", rank(opportunity(), NOW))

    def test_free_application_is_not_a_fee(self):
        self.assertIsNotNone(rank(opportunity(description="No debes pagar cuota de inscripción"), NOW))
        self.assertIsNotNone(rank(opportunity(description="The application fee is $0"), NOW))

    def test_precise_craft_title_can_stand_alone(self):
        self.assertIsNotNone(rank(opportunity(title="Patternmaker"), NOW))
        self.assertIsNotNone(rank(opportunity(title="Patronista"), NOW))
        self.assertIsNone(rank(opportunity(title="Technical Designer"), NOW))

    def test_general_fashion_mention_needs_specialized_context(self):
        general = opportunity(title="Paid Media Strategist, Fashion", description="E-commerce advertising")
        specialized = opportunity(title="Fashion Marketing Director", description="Lead the launch of bridal collections")
        self.assertIsNone(rank(general, NOW))
        self.assertIsNotNone(rank(specialized, NOW))


class CollectionTest(unittest.TestCase):
    def test_duplicates_across_sources_prefer_verified_higher_score(self):
        sources = {
            "a": source(lambda _: [opportunity("a:1", url="https://example.org/jobs/1?utm_source=a")]),
            "b": source(lambda _: [opportunity("b:1", url="https://example.org/jobs/1", clearApplication=False)]),
        }
        result = collect(sources, {}, NOW)
        self.assertEqual([row["id"] for row in result["opportunities"]], ["a:1"])
        self.assertEqual([status["count"] for status in result["sources"]], [1, 0])

    def test_partial_failure_keeps_only_unexpired_recent_rows(self):
        previous = collect({"a": source(lambda _: [
            opportunity("a:1"),
            opportunity("a:2", url="https://example.org/jobs/2", deadline="2026-11-07T01:00:00Z"),
        ])}, {}, NOW)

        def failure(_):
            raise TimeoutError("offline")

        result = collect({"a": source(failure), "b": source(lambda _: [])}, previous, NOW + timedelta(hours=6))
        self.assertEqual([s["status"] for s in result["sources"]], ["error", "ok"])
        self.assertEqual([row["id"] for row in result["opportunities"]], ["a:1"])
        self.assertTrue(result["opportunities"][0]["pending"])
        self.assertNotEqual(result["lastSuccessAt"], previous["lastSuccessAt"])
        later = collect({"a": source(failure)}, result, NOW + timedelta(hours=49))
        self.assertEqual(later["opportunities"], [])
        self.assertEqual(later["lastSuccessAt"], result["lastSuccessAt"])

    def test_healthy_empty_clears_old_rows_and_updates_timestamp(self):
        sources = {"a": source(lambda _: [])}
        previous = collect({"a": source(lambda _: [opportunity("a:1")])}, {}, NOW)
        result = collect(sources, previous, NOW)
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(result["sources"][0]["status"], "ok")
        self.assertEqual(result["sources"][0]["count"], 0)

    def test_newest_breaks_score_tie(self):
        sources = {"a": source(lambda _: [
            opportunity("a:1"),
            opportunity("a:2", title="Haute couture designer", url="https://example.org/jobs/2",
                        publishedAt="2026-11-04T00:00:00Z"),
        ])}
        result = collect(sources, {}, NOW)
        self.assertEqual([row["id"] for row in result["opportunities"]], ["a:2", "a:1"])


if __name__ == "__main__":
    unittest.main()
