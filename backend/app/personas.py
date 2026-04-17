from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


FieldType = Literal["string", "boolean", "enum", "string_list", "text"]


@dataclass(frozen=True)
class QuestionnaireField:
    key: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: str | None = None
    options: list[str] | None = None  # for enum
    help: str | None = None


@dataclass(frozen=True)
class PersonaQuestionnaire:
    key: str
    label: str
    goal: str
    fields: list[QuestionnaireField]


def list_personas() -> list[PersonaQuestionnaire]:
    """
    Product-facing questionnaires. These are the inputs the platform needs to
    make agent outputs materially more accurate without the user wiring tools.
    """

    common = [
        QuestionnaireField("company", "Company", "string", required=False, placeholder="Acme Inc"),
        QuestionnaireField("region", "Region", "enum", required=True, options=["EU", "EEA", "UK", "US", "Other"]),
        QuestionnaireField(
            "data_types",
            "Data types",
            "string_list",
            required=True,
            placeholder="PII, biometric, chat logs",
            help="Comma-separated list.",
        ),
        QuestionnaireField("data_retention", "Data retention", "string", required=False, placeholder="e.g., 6 months"),
        QuestionnaireField("dpia_done", "DPIA completed", "boolean", required=False),
    ]

    return [
        PersonaQuestionnaire(
            key="founder_pm",
            label="Founder / PM shipping AI features",
            goal="Decide whether you can ship, what must be true, and what to build next.",
            fields=common
            + [
                QuestionnaireField("feature_stage", "Feature stage", "enum", required=True, options=["Idea", "Beta", "GA"]),
                QuestionnaireField("user_impact", "User impact", "enum", required=True, options=["Low", "Medium", "High"]),
                QuestionnaireField("uses_vendors", "Uses vendors/processors", "boolean", required=False),
                QuestionnaireField("notes", "Notes", "text", required=False, placeholder="Anything else relevant."),
            ],
        ),
        PersonaQuestionnaire(
            key="security",
            label="Security / compliance lead",
            goal="Identify controls gaps, security obligations, and evidence required for audit.",
            fields=common
            + [
                QuestionnaireField("access_controls", "Access controls in place", "enum", required=False, options=["Unknown", "Basic", "Strong"]),
                QuestionnaireField("encryption_at_rest", "Encryption at rest", "boolean", required=False),
                QuestionnaireField("encryption_in_transit", "Encryption in transit", "boolean", required=False),
                QuestionnaireField("logging_monitoring", "Logging/monitoring", "enum", required=False, options=["Unknown", "Basic", "Mature"]),
                QuestionnaireField("incident_response", "Incident response process", "boolean", required=False),
            ],
        ),
        PersonaQuestionnaire(
            key="legal_ops",
            label="Legal ops / privacy officer",
            goal="Produce a defensible compliance narrative with the right artifacts and lawful basis.",
            fields=common
            + [
                QuestionnaireField(
                    "lawful_basis",
                    "Lawful basis",
                    "enum",
                    required=False,
                    options=["Unknown", "Consent", "Contract", "Legal obligation", "Legitimate interests", "Public task", "Vital interests"],
                ),
                QuestionnaireField("privacy_notice_ready", "Privacy notice updated", "boolean", required=False),
                QuestionnaireField("dpa_in_place", "DPAs in place with processors", "boolean", required=False),
                QuestionnaireField("ropa_ready", "RoPA/records ready", "boolean", required=False),
            ],
        ),
        PersonaQuestionnaire(
            key="sales_eng",
            label="Sales engineer (compliance questionnaires)",
            goal="Generate answer-ready responses for customer due diligence and questionnaires.",
            fields=common
            + [
                QuestionnaireField("customer_industry", "Customer industry", "string", required=False, placeholder="e.g., Healthcare"),
                QuestionnaireField("hosting_region", "Hosting region", "enum", required=False, options=["EU", "US", "Multi-region", "Unknown"]),
                QuestionnaireField("subprocessors", "Subprocessors", "string_list", required=False, placeholder="AWS, OpenAI, ..."),
                QuestionnaireField("security_certifications", "Security certifications", "string_list", required=False, placeholder="SOC2, ISO27001"),
            ],
        ),
    ]


def personas_to_dict() -> dict[str, Any]:
    out = {"personas": []}
    for p in list_personas():
        out["personas"].append(
            {
                "key": p.key,
                "label": p.label,
                "goal": p.goal,
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "type": f.type,
                        "required": f.required,
                        "placeholder": f.placeholder,
                        "options": f.options,
                        "help": f.help,
                    }
                    for f in p.fields
                ],
            }
        )
    return out

