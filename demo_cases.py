"""Original physics and mathematics examples and deterministic, simulated model responses."""
from workflow import CONTROLLED_ERROR_CATEGORIES as CATEGORIES

SAMPLES = (
    {
        "id": "PHY-01", "subject": "Physics", "title": "Cart on a straight track",
        "question": "A cart travels at a steady 2 m/s for 90 s. How far does it go?",
        "evidence": {
            "E1": "For steady speed, distance = speed × elapsed time.",
            "E2": "The speed is 2 m/s. The elapsed time is 90 s, or 1.5 min. Use seconds with m/s.",
        },
        "reference": "2 m/s × 90 s = 180 m.",
    },
    {
        "id": "PHY-02", "subject": "Physics", "title": "Frictionless puck",
        "question": "A puck moves at 3 m/s on a level frictionless table with zero net force. What is its speed after 5 s?",
        "evidence": {"E1": "With zero net force, acceleration is zero.",
                     "E2": "When acceleration is zero, the puck keeps its initial velocity."},
        "reference": "The puck is still moving at 3 m/s.",
    },
    {
        "id": "MATH-01", "subject": "Mathematics", "title": "Integrating an absolute value",
        "question": "Evaluate the integral of |x − 1| from −1 to 3. Use the formula, without a graph or a table of values.",
        "evidence": {
            "E1": "On [−1, 1], |x − 1| = 1 − x. On [1, 3], |x − 1| = x − 1.",
            "E2": "The two nonnegative pieces each have integral 2.",
            "E3": "The question supplies no graph, table, or numerical integration output.",
        },
        "reference": "Split the integral at x = 1. The result is 2 + 2 = 4.",
    },
    {
        "id": "MATH-02", "subject": "Mathematics", "title": "Eigenvalues of a symmetric matrix",
        "question": "Find both eigenvalues of the matrix with rows (4, 1) and (1, 4). Use only the given entries.",
        "evidence": {
            "E1": "The characteristic polynomial is (4 − λ)² − 1 = λ² − 8λ + 15.",
            "E2": "It factors as (λ − 3)(λ − 5).",
            "E3": "The problem supplies no solver output, plot, or list of eigenvalues.",
        },
        "reference": "Solve (4 − λ)² = 1. The eigenvalues are 3 and 5.",
    },
)

# Each variant is a fixture, with independent reference evidence above.
# The first case deliberately shows a plausible bad candidate and a bad annotation.
VARIANTS = {
    ("PHY-01", "C4"): (
        ("The cart moves at 3 m/s for 1.5 min. Multiplying 3 by 1.5 gives a distance of 4.5 m.",
         "Multiplying 3 by 1.5", "The calculation uses minutes with a speed given per second.",
         "Distance equals speed multiplied by time in compatible units.", "Use 90 s instead of 1.5 min."),
        ("The cart moves at 2 m/s for 1.5 min. Multiplying 2 by 1.5 gives a distance of 3 m.",
         "Multiplying 2 by 1.5", "The elapsed time is in minutes while the speed is in meters per second.",
         "Distance equals speed multiplied by time in compatible units.", "Convert 1.5 min to 150 s."),
    ),
    ("PHY-02", "C1"): (
        ("A net force is needed to keep the puck moving. With zero net force, it stops within 5 s.",
         "A net force is needed to keep the puck moving", "Zero net force implies zero acceleration.",
         "Newton's first law preserves velocity in the absence of net force.", "Keep the speed at 3 m/s."),
        ("Zero net force makes the puck accelerate in its direction of motion, so its speed exceeds 3 m/s.",
         "Zero net force makes the puck accelerate", "There is no net force to produce acceleration.",
         "A nonzero acceleration requires a nonzero net force.", "Set acceleration to zero and retain 3 m/s."),
    ),
    ("MATH-01", "C2"): (
        ("On the entire interval, replace |x − 1| with x − 1. Its antiderivative takes the same value at −1 and 3, so the integral is 0.",
         "On the entire interval, replace |x − 1| with x − 1", "That substitution fails when x is less than 1.",
         "The sign of the expression inside the absolute value determines its formula.", "Split at x = 1 and add the two integrals."),
        ("Since |x − 1| equals 1 − x, use that integrand on [−1, 3]. The integral is 0.",
         "use that integrand on [−1, 3]", "The formula 1 − x is valid only at x ≤ 1.",
         "Apply each branch of the absolute value on its own interval.", "Integrate 1 − x to the left of 1 and x − 1 to its right."),
    ),
    ("MATH-01", "C3"): (
        ("Read the integral value from the supplied table of cumulative areas.",
         "the supplied table of cumulative areas", "No cumulative area table is provided.",
         "A solution can only use the inputs available in the problem.", "Evaluate the two exact integrals."),
        ("Use the graph provided with the problem and add its two triangular areas.",
         "the graph provided with the problem", "No graph accompanies the problem.",
         "A graphical measurement requires an available graph or a graph derived from the formula.", "Use the explicit piecewise formula."),
    ),
    ("MATH-02", "C3"): (
        ("Read the two eigenvalues from the attached numerical eigensolver output.",
         "the attached numerical eigensolver output", "There is no solver result attached.",
         "Read eigenvalues only from available data or compute them from the matrix.", "Calculate the characteristic polynomial."),
        ("Read the intersections with the horizontal axis from the supplied characteristic-polynomial plot.",
         "the supplied characteristic-polynomial plot", "The question supplies only the matrix.",
         "A root cannot be read from an unavailable plot.", "Solve the polynomial directly."),
    ),
    ("MATH-02", "C4"): (
        ("The characteristic polynomial is (4 − λ)² − 1 = λ² − 8λ + 14. Its roots are 4 ± √2.",
         "(4 − λ)² − 1 = λ² − 8λ + 14", "The constant term must be 16 − 1 = 15.",
         "Equivalent polynomial forms must have equal coefficients.", "Use a constant term of 15; the roots are 3 and 5."),
        ("Setting (4 − λ)² − 1 = 0 gives (4 − λ)² = 4, so the eigenvalues are 2 and 6.",
         "gives (4 − λ)² = 4", "Moving the constant to the other side gives 1.",
         "An equality remains valid when the same quantity is added to both sides.", "Solve (4 − λ)² = 1 for λ = 3 or 5."),
    ),
}

FINAL_ANNOTATION = {
    "error_span_or_step": "Multiplying 2 by 1.5 gives a distance of 3 m",
    "error_explanation": "The calculation combines 2 meters per second with 1.5 minutes without converting the time.",
    "scientific_constraint": "Use the same time unit in the speed denominator and the elapsed time.",
    "minimal_repair": "Convert 1.5 min to 90 s, then calculate 2 m/s × 90 s = 180 m.",
}


def inject(sample_id, category, reinjection=False):
    first, retry = VARIANTS[sample_id, category]
    candidate, span, explanation, constraint, repair = retry if reinjection else first
    return {
        "candidate_output": candidate,
        "suggested_judgment": "clear_violation",
        "suggested_errors": [{
            "error_span_or_step": span,
            "error_category": CATEGORIES[category],
            "error_subtype": "unit conversion" if sample_id == "PHY-01" else CATEGORIES[category].lower(),
            "error_explanation": explanation,
            "scientific_constraint": constraint,
            "applicability_conditions": "Use the conditions and measurements given in the question.",
            "minimal_repair": repair,
        }],
        "uncertainties": [],
    }


def revision_reply(sample):
    error = sample["ai_preannotation"]["suggested_errors"][0]
    if sample["id"] == "PHY-01" and len(sample["candidates"]) > 1:
        return FINAL_ANNOTATION.copy()
    return {
        "error_span_or_step": error["error_span_or_step"],
        "error_explanation": error["error_explanation"],
        "scientific_constraint": error["scientific_constraint"],
        "minimal_repair": sample["reference"],
    }
