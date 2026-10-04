"""Load ~50 realistic sample contacts into a development instance (Phase 1).

    make seed I=dev            # add sample contacts
    make seed I=dev RESET=1    # delete all contacts first, then add samples

Refuses to run when APP_ENV=production (I-05). All email domains use the
reserved ``.example`` TLD, so nothing here can reach a real person.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.contacts import create_contact
from app.db import create_db_engine, make_session_factory
from app.migrate import ensure_contact_types, upgrade_to_head
from app.models import Contact, ContactType
from app.schemas import ContactCreate


class ProductionRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Sample:
    name: str
    type: str
    company: str
    title: str | None = None
    team: str | None = None
    department: str | None = None
    manager: str | None = None
    works_on: str | None = None
    notes: str | None = None
    email: bool = True
    phone: str | None = None
    slack: bool = False
    location: str | None = None
    extra_emails: tuple[str, ...] = field(default_factory=tuple)
    birthday: str | None = None  # C-20: "YYYY-MM-DD" or "--MM-DD"


ACME = "Acme Health"

# C-19: one (made-up) office per company, spread over time zones for a future map.
OFFICES: dict[str, dict[str, str]] = {
    ACME: {"street": "200 Commerce Pkwy, Suite 400", "city": "Atlanta", "region": "GA",
           "postal_code": "30303"},
    "Northside Clinic": {"street": "51 Northside Dr", "city": "Atlanta", "region": "GA",
                         "postal_code": "30318"},
    "Peachtree Labs": {"street": "3100 Industrial Blvd", "city": "Duluth", "region": "GA",
                       "postal_code": "30096"},
    "Buford Family Medicine": {"street": "12 Main St", "city": "Buford", "region": "GA",
                               "postal_code": "30518"},
    "Gwinnett Health Partners": {"street": "700 Hospital Ave", "city": "Lawrenceville",
                                 "region": "GA", "postal_code": "30046"},
    "InterLink HL7 Services": {"street": "1600 Market St", "city": "Denver", "region": "CO",
                               "postal_code": "80202"},
    "CloudVault Hosting": {"street": "400 Harbor Way", "city": "Seattle", "region": "WA",
                           "postal_code": "98101"},
    "SecureScan Audits": {"street": "88 Congress Ave", "city": "Austin", "region": "TX",
                          "postal_code": "78701"},
    "LabSupply Direct": {"street": "2200 Lake St", "city": "Chicago", "region": "IL",
                         "postal_code": "60601"},
    "UX Research Co": {"street": "150 King St W", "city": "Toronto", "region": "ON",
                       "postal_code": "M5H 1J9", "country": "Canada"},
}  # fmt: skip


def _employees() -> list[Sample]:
    eng, prod = "Engineering", "Product"
    return [
        Sample(
            "Priya Raman",
            "Employee",
            ACME,
            "VP Engineering",
            "Engineering Leadership",
            eng,
            works_on="Platform strategy, engineering hiring",
            slack=True,
            phone="404-555-0101",
            birthday="1978-11-02",
        ),
        Sample(
            "Maria Lopez",
            "Employee",
            ACME,
            "Engineering Manager",
            "Data Platform",
            eng,
            "Priya Raman",
            "Lab results pipeline, data warehouse, HL7 ingestion",
            slack=True,
            phone="404-555-0102",
            birthday="--06-21",
        ),
        Sample(
            "Dev Patel",
            "Employee",
            ACME,
            "Senior Data Engineer",
            "Data Platform",
            eng,
            "Maria Lopez",
            "Owns the lab results pipeline (HL7 ORU parsing)",
            slack=True,
        ),
        Sample(
            "Chen Wei",
            "Employee",
            ACME,
            "Data Engineer",
            "Data Platform",
            eng,
            "Maria Lopez",
            "Warehouse models, reporting feeds",
        ),
        Sample(
            "Olivia Brooks",
            "Employee",
            ACME,
            "Analytics Engineer",
            "Data Platform",
            eng,
            "Maria Lopez",
            "Quality dashboards, turnaround-time metrics",
        ),
        Sample(
            "Samir Haddad",
            "Employee",
            ACME,
            "Data Engineer",
            "Data Platform",
            eng,
            "Maria Lopez",
            "FHIR export API",
            notes="Prefers Slack over email",
        ),
        Sample(
            "James Carter",
            "Employee",
            ACME,
            "Engineering Manager",
            "Lab Integrations",
            eng,
            "Priya Raman",
            "LIS and instrument interfaces",
            slack=True,
        ),
        Sample(
            "Nina Petrova",
            "Employee",
            ACME,
            "Integration Engineer",
            "Lab Integrations",
            eng,
            "James Carter",
            "Instrument middleware, ASTM interfaces",
        ),
        Sample(
            "Luis Ortega",
            "Employee",
            ACME,
            "Integration Engineer",
            "Lab Integrations",
            eng,
            "James Carter",
            "Reference lab connections (Quest, Labcorp)",
        ),
        Sample(
            "Grace Kim",
            "Employee",
            ACME,
            "QA Engineer",
            "Lab Integrations",
            eng,
            "James Carter",
            "Validation protocols, CLIA test evidence",
        ),
        Sample(
            "Aisha Bello",
            "Employee",
            ACME,
            "Engineering Manager",
            "Web Apps",
            eng,
            "Priya Raman",
            "Patient portal, provider ordering UI",
            slack=True,
        ),
        Sample(
            "Tom Nguyen",
            "Employee",
            ACME,
            "Frontend Engineer",
            "Web Apps",
            eng,
            "Aisha Bello",
            "Ordering workflow, accessibility fixes",
        ),
        Sample(
            "Rachel Stein",
            "Employee",
            ACME,
            "Full-stack Engineer",
            "Web Apps",
            eng,
            "Aisha Bello",
            "Results viewer, PDF reports",
        ),
        Sample(
            "Kwame Mensah",
            "Employee",
            ACME,
            "Site Reliability Engineer",
            "Infrastructure",
            eng,
            "Priya Raman",
            "Kubernetes, on-call rotation, HIPAA logging",
        ),
        Sample(
            "Daniel Kim",
            "Employee",
            ACME,
            "Head of Product",
            "Product Leadership",
            prod,
            works_on="Roadmap, pricing",
            slack=True,
            phone="404-555-0110",
        ),
        Sample(
            "Emily Walsh",
            "Employee",
            ACME,
            "Product Manager",
            "Product",
            prod,
            "Daniel Kim",
            "Provider ordering experience",
        ),
        Sample(
            "Marcus Reed",
            "Employee",
            ACME,
            "Product Manager",
            "Product",
            prod,
            "Daniel Kim",
            "Lab network partnerships",
        ),
        Sample(
            "Hannah Liu",
            "Employee",
            ACME,
            "Product Designer",
            "Design",
            prod,
            "Daniel Kim",
            "Design system, usability studies",
        ),
        Sample(
            "Fatima Zahra",
            "Employee",
            ACME,
            "Regulatory Affairs Lead",
            "Quality & Regulatory",
            "Operations",
            works_on="FDA submissions, ISO 13485 audits",
            notes="Helped with the 510(k) pre-submission",
        ),
        Sample(
            "Ben Okafor",
            "Employee",
            ACME,
            "Security Engineer",
            "Security",
            eng,
            "Priya Raman",
            "SOC 2, pen test remediation",
        ),
        Sample(
            "Laura Schmidt",
            "Employee",
            ACME,
            "Customer Success Manager",
            "Customer Success",
            "Operations",
            works_on="Northside Clinic and Peachtree Labs accounts",
            phone="404-555-0120",
        ),
        Sample(
            "Diego Alvarez",
            "Employee",
            ACME,
            "Solutions Engineer",
            "Customer Success",
            "Operations",
            "Laura Schmidt",
            "Implementation for new clinic customers",
        ),
        Sample(
            "Anita Desai",
            "Employee",
            ACME,
            "SRE",
            "Infrastructure",
            eng,
            "Kwame Mensah",
            "Backups, disaster recovery drills",
        ),
        Sample(
            "Jorge Silva",
            "Employee",
            ACME,
            "Mobile Engineer",
            "Web Apps",
            eng,
            "Aisha Bello",
            "Courier specimen-pickup app",
        ),
        Sample(
            "Mei Lin",
            "Employee",
            ACME,
            "Data Engineering Intern",
            "Data Platform",
            eng,
            "Maria Lopez",
            "Test-code mapping cleanup",
        ),
        Sample(
            "Paul Bennett",
            "Employee",
            ACME,
            "CFO",
            "Finance",
            "Finance",
            works_on="Budget approvals, vendor contracts",
        ),
        Sample(
            "Zoe Carter",
            "Employee",
            ACME,
            "Contracts Manager",
            "Finance",
            "Finance",
            "Paul Bennett",
            "Vendor MSAs and BAAs",
            email=True,
        ),
    ]


def _customers() -> list[Sample]:
    return [
        Sample(
            "Dr. Angela Foster",
            "Customer",
            "Northside Clinic",
            "Medical Director",
            works_on="Executive sponsor for lab ordering rollout",
            phone="770-555-0131",
        ),
        Sample(
            "Kevin Tran",
            "Customer",
            "Northside Clinic",
            "IT Manager",
            works_on="EHR integration, SSO",
            notes="Met at HIMSS; asked about HL7 v2.5.1",
        ),
        Sample(
            "Monica Hayes",
            "Customer",
            "Northside Clinic",
            "Practice Administrator",
            email=False,
            phone="770-555-0133",
        ),
        Sample(
            "Robert Lin",
            "Customer",
            "Peachtree Labs",
            "Lab Director",
            works_on="Customer sponsor, Q4 LIS integration",
            phone="678-555-0141",
        ),
        Sample(
            "Sofia Rossi",
            "Customer",
            "Peachtree Labs",
            "LIS Administrator",
            works_on="Interface specs, test code mapping",
        ),
        Sample(
            "Jamal Wright",
            "Customer",
            "Peachtree Labs",
            "Quality Manager",
            works_on="CAP inspection readiness",
        ),
        Sample(
            "Ellen Park",
            "Customer",
            "Buford Family Medicine",
            "Office Manager",
            works_on="Pilot site for provider ordering",
            location="Buford, GA",
        ),
        Sample(
            "Dr. Omar Siddiqui",
            "Customer",
            "Buford Family Medicine",
            "Physician Owner",
            notes="Prefers phone calls",
            email=False,
            phone="770-555-0152",
        ),
        Sample(
            "Heather Collins",
            "Customer",
            "Gwinnett Health Partners",
            "VP Clinical Operations",
            works_on="Enterprise contract renewal",
        ),
        Sample(
            "Victor Chen",
            "Customer",
            "Gwinnett Health Partners",
            "Integration Analyst",
            works_on="ADT feeds, results routing",
        ),
        Sample("Priscilla Adams", "Customer", "Gwinnett Health Partners", "Procurement Lead"),
        Sample(
            "Dr. Susan Clark",
            "Customer",
            "Northside Clinic",
            "Pathologist",
            works_on="Reviews abnormal result flags",
        ),
        Sample(
            "Brian Howell",
            "Customer",
            "Peachtree Labs",
            "Courier Supervisor",
            email=False,
            phone="678-555-0149",
        ),
    ]


def _vendors() -> list[Sample]:
    return [
        Sample(
            "Greg Hoffman",
            "Vendor",
            "InterLink HL7 Services",
            "Account Executive",
            works_on="Interface engine licensing",
            phone="800-555-0161",
        ),
        Sample(
            "Yuki Tanaka",
            "Vendor",
            "InterLink HL7 Services",
            "Implementation Lead",
            works_on="Vendor PM for the Q4 LIS integration",
        ),
        Sample(
            "Carlos Mendes",
            "Vendor",
            "CloudVault Hosting",
            "Technical Account Manager",
            works_on="HIPAA-eligible hosting, BAA",
        ),
        Sample("Abigail Moore", "Vendor", "CloudVault Hosting", "Support Engineer"),
        Sample(
            "Ivan Kowalski",
            "Vendor",
            "SecureScan Audits",
            "Lead Auditor",
            works_on="SOC 2 Type II audit",
        ),
        Sample("Nora Fitzgerald", "Vendor", "SecureScan Audits", "Engagement Manager", email=False),
        Sample(
            "Pete Sullivan",
            "Vendor",
            "LabSupply Direct",
            "Sales Rep",
            works_on="Reagents and consumables",
            phone="866-555-0171",
        ),
        Sample(
            "Lena Novak",
            "Vendor",
            "UX Research Co",
            "Research Lead",
            works_on="Provider usability study",
        ),
        Sample(
            "Andre Baptiste",
            "Vendor",
            "Regulatory Partners LLC",
            "Consultant",
            works_on="FDA 510(k) strategy",
            notes="Introduced by Fatima Zahra",
        ),
        Sample(
            "Owen Price",
            "Vendor",
            "LabSupply Direct",
            "Regional Manager",
            works_on="Escalations for backordered supplies",
        ),
    ]


def samples() -> list[Sample]:
    return _employees() + _customers() + _vendors()


def _email_for(sample: Sample) -> str:
    local = ".".join(
        part.lower().strip(".") for part in sample.name.replace("Dr. ", "").split() if part
    )
    domain = "".join(ch for ch in sample.company.lower() if ch.isalnum()) + ".example"
    return f"{local}@{domain}"


def seed(session: Session, *, phone_region: str = "US") -> int:
    """Insert the sample contacts; managers are linked by name. Returns rows added."""
    type_ids: dict[str, int] = {}
    for name in ("Employee", "Customer", "Vendor"):
        existing = session.scalars(select(ContactType).where(ContactType.name == name)).first()
        if existing is None:
            existing = ContactType(name=name, sort_order=100)
            session.add(existing)
            session.flush()
        type_ids[name] = existing.id

    ids: dict[str, int] = {}
    for s in samples():
        emails = [{"email": _email_for(s), "label": "work"}] if s.email else []
        contact = create_contact(
            session,
            ContactCreate.model_validate(
                {
                    "display_name": s.name,
                    "contact_type_id": type_ids[s.type],
                    "company": s.company,
                    "title": s.title,
                    "team": s.team,
                    "department": s.department,
                    "location": s.location or ("Atlanta, GA" if s.company == ACME else None),
                    "manager_id": ids.get(s.manager) if s.manager else None,
                    "works_on": s.works_on,
                    "notes": s.notes,
                    "emails": emails,
                    "phones": [{"number": s.phone, "label": "work"}] if s.phone else [],
                    "addresses": (
                        [{"label": "work", **OFFICES[s.company]}] if s.company in OFFICES else []
                    ),
                    "slack_handle": s.name.split()[0].lower() if s.slack else None,
                    "birthday": s.birthday,
                }
            ),
            phone_region=phone_region,
        )
        ids[s.name] = contact.id
    return len(ids)


def reset(session: Session) -> int:
    """Delete every contact (emails/phones cascade)."""
    result = session.execute(delete(Contact))
    return int(getattr(result, "rowcount", 0))


def run(settings: Settings, *, do_reset: bool = False) -> int:
    if settings.is_production:
        raise ProductionRefused(
            f"Refusing to seed or reset '{settings.instance_name}': APP_ENV=production (I-05)"
        )
    upgrade_to_head(settings)
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            ensure_contact_types(session, settings.contact_types)
            if do_reset:
                reset(session)
            count = seed(session, phone_region=settings.phone_region)
            session.commit()
            return count
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load sample contacts (never in production)")
    parser.add_argument("--reset", action="store_true", help="delete all contacts first")
    args = parser.parse_args(argv)
    try:
        count = run(load_settings(), do_reset=args.reset)
    except ProductionRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Added {count} sample contacts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
