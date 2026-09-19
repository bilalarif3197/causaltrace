"""Built-in demonstration cases.

These are synthetic narratives written in the style of published case reports.
They are NOT real patient data and carry no patient-identifiable information.

Drugs are referred to by letter plus therapeutic class ("Drug A, an oral
antifungal agent") rather than by brand or product name. That follows the
challenge scope rule -- work at the drug-class level, do not present
conclusions about named products -- and it keeps the demo focused on the
reasoning rather than on whether a particular product is hepatotoxic.

The three cases are chosen to exercise different failure modes:

  dili-ambiguous-001   two plausible culprit drugs plus an infection. The
                       system should refuse to pick a winner.
  cutaneous-clear-002  positive dechallenge AND positive rechallenge. A case
                       where high confidence is actually warranted.
  aki-sparse-003       an information-poor report. Most items are UNKNOWN and
                       the score is nearly uninformative -- which the UI must
                       say out loud rather than hide behind a number.
"""

from __future__ import annotations

from schemas.models import ExampleCase

DILI_AMBIGUOUS = ExampleCase(
    case_id="dili-ambiguous-001",
    title="Acute liver injury with two candidate drugs",
    description=(
        "A patient on two potentially hepatotoxic drugs who also has pneumonia. "
        "Dechallenge is positive for one drug, but a competing explanation is documented "
        "and key tests were never done."
    ),
    suspected_drug="Drug A",
    adverse_event="Acute liver injury",
    is_ambiguous=True,
    narrative=(
        "A 58-year-old man with type 2 diabetes and hypertension was started on Drug A, an oral "
        "antifungal agent, on 3 January for onychomycosis. His baseline liver function tests were "
        "normal, with ALT 28 U/L and AST 24 U/L. On 8 January he was prescribed Drug B, a macrolide "
        "antibiotic, for a productive cough and fever; a chest radiograph showed a right lower lobe "
        "infiltrate consistent with community-acquired pneumonia.\n\n"
        "On 18 January the patient presented with malaise, nausea and dark urine. Laboratory testing "
        "showed ALT 642 U/L, AST 518 U/L, alkaline phosphatase 180 U/L and total bilirubin 3.1 mg/dL. "
        "Abdominal ultrasound demonstrated a normal biliary tree without obstruction. Hepatitis A, B "
        "and C serologies were not obtained.\n\n"
        "Drug A was discontinued on 20 January. Drug B was continued to complete a ten-day course. "
        "The patient's fever resolved and the pneumonia improved over the following week. Liver "
        "enzymes declined gradually and had normalised by 10 February, with ALT 31 U/L.\n\n"
        "The patient was not re-exposed to Drug A. No serum drug concentrations were measured. He had "
        "received a different antifungal agent several years earlier without complication."
    ),
)

CUTANEOUS_CLEAR = ExampleCase(
    case_id="cutaneous-clear-002",
    title="Maculopapular rash with positive rechallenge",
    description=(
        "An inadvertent rechallenge reproduced the reaction. This is the rare case where the "
        "evidence genuinely supports a high-confidence assessment."
    ),
    suspected_drug="Drug C",
    adverse_event="Maculopapular rash",
    is_ambiguous=False,
    narrative=(
        "A 34-year-old woman with no significant medical history was prescribed Drug C, a sulfonamide "
        "antimicrobial, for an uncomplicated urinary tract infection. She took the first dose on the "
        "morning of 2 March. On 5 March she developed a pruritic maculopapular rash over her trunk and "
        "upper arms, documented on examination by her general practitioner and photographed in the "
        "clinical record. She was taking no other medications.\n\n"
        "Drug C was stopped on 5 March. The rash faded over four days and had fully resolved by "
        "9 March.\n\n"
        "Six weeks later, unaware of the earlier reaction, a different clinician prescribed the same "
        "agent for a recurrent urinary tract infection. The patient took a single dose on 21 April and "
        "the maculopapular rash recurred within twelve hours, again affecting the trunk and upper arms. "
        "The drug was stopped immediately and the rash resolved within three days.\n\n"
        "The patient reported that she had developed a rash after a sulfonamide-containing antibiotic "
        "as a teenager, though no records were available. Cutaneous reactions to this drug class are "
        "well described in the published literature."
    ),
)

AKI_SPARSE = ExampleCase(
    case_id="aki-sparse-003",
    title="Acute kidney injury, minimally reported",
    description=(
        "A short report missing almost everything decisive. Seven of ten Naranjo items are "
        "UNKNOWN and the resulting score spans four bands, so the headline number means little."
    ),
    suspected_drug="Drug D",
    adverse_event="Acute kidney injury",
    is_ambiguous=True,
    narrative=(
        "A 71-year-old patient developed acute kidney injury during hospital admission. The patient had "
        "been receiving Drug D, an intravenous antibiotic, as part of treatment for a documented "
        "bloodstream infection. Serum creatinine rose from 1.0 mg/dL to 2.4 mg/dL over three days. The "
        "patient was also receiving intravenous contrast for imaging during the same period and was "
        "hypotensive on the second day of admission. The outcome after the admission was not reported."
    ),
)

TMPSMX_DILI = ExampleCase(
    case_id="tmpsmx-dili-004",
    title="TMP-SMX and acute liver injury",
    description=(
        "A named-generic case with a positive dechallenge, a documented over-the-counter "
        "alternative exposure, and no rechallenge. The reviewer has to weigh the antibiotic "
        "against low-dose acetaminophen."
    ),
    suspected_drug="Trimethoprim-sulfamethoxazole (TMP-SMX)",
    adverse_event="Acute liver injury",
    is_ambiguous=True,
    indication="Uncomplicated urinary tract infection",
    age="34",
    sex="Female",
    concomitant_medications="Acetaminophen as needed; combined oral contraceptive",
    comorbidities="None significant",
    narrative=(
        "A 34-year-old woman with no significant past medical history began "
        "trimethoprim-sulfamethoxazole (TMP-SMX) 160/800 mg twice daily on March 2 for an "
        "uncomplicated urinary tract infection. She was also taking a combined oral "
        "contraceptive, and reported taking acetaminophen intermittently for headache at a "
        "dose of 500 to 1,000 mg per day. She did not drink alcohol.\n\n"
        "On March 7 she developed fatigue and nausea. She completed the ten-day antibiotic "
        "course on March 11. Symptoms persisted, and on March 16 she presented to her "
        "physician with malaise and scleral icterus. Laboratory testing that day showed ALT "
        "684 U/L, AST 512 U/L, alkaline phosphatase 142 U/L and total bilirubin 2.8 mg/dL. "
        "Liver function had not been measured before she started the antibiotic.\n\n"
        "Hepatitis A, B and C serologies were negative. Anti-nuclear and anti-smooth muscle "
        "antibodies were negative. Abdominal ultrasound showed a normal liver echotexture "
        "with patent vessels and no biliary dilatation. Acetaminophen was discontinued at "
        "presentation; no serum acetaminophen concentration was obtained.\n\n"
        "By March 23 liver enzymes had begun to improve, and by late April liver tests had "
        "returned to normal. The patient was advised to avoid TMP-SMX in future and was not "
        "re-exposed. She reported no previous reaction to sulfonamide antibiotics."
    ),
)

EXAMPLE_CASES: list[ExampleCase] = [TMPSMX_DILI, DILI_AMBIGUOUS, CUTANEOUS_CLEAR, AKI_SPARSE]

CASES_BY_ID = {c.case_id: c for c in EXAMPLE_CASES}


def get(case_id: str) -> ExampleCase | None:
    return CASES_BY_ID.get(case_id)


def match_narrative(narrative: str) -> ExampleCase | None:
    """Identify a built-in case from its narrative text.

    Lets mock mode still work when the frontend posts a narrative the user
    loaded from an example (and possibly whitespace-mangled) without an id.
    """
    needle = " ".join(narrative.split())
    for case in EXAMPLE_CASES:
        if " ".join(case.narrative.split()) == needle:
            return case
    return None
