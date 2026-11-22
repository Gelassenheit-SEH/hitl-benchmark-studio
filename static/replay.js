(function script() {
    "use strict";

    const el = (selector) => document.querySelector(selector);
    const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => (
        {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]
    ));
    const labels = {
        generated: ["Model generated", "Generated", "Model"],
        sent_back: ["Reviewer sent back", "Sent back", "Human"],
        regenerated: ["Model regenerated", "Regenerated", "Model"],
        revision_requested: ["Reviewer requested field revision", "Feedback", "Human"],
        annotation_revised: ["Model revised the annotation", "Revised", "Model"],
        human_override: ["Reviewer changed annotation", "Override", "Human"],
        released: ["Accepted and issued", "Issued", "Human"],
    };
    const fieldNames = {
        error_category: "Error category",
        error_span_or_step: "Error location",
        error_explanation: "Explanation",
        scientific_constraint: "Scientific constraint",
        applicability_conditions: "Applicability conditions",
        minimal_repair: "Minimal repair",
    };
    let cases = [];
    let caseIndex = 0;
    let stepIndex = 0;

    function plainLabel(value) {
        const words = String(value ?? "").replaceAll("_", " ");
        return words.charAt(0).toUpperCase() + words.slice(1);
    }

    function fieldValue(key, value) {
        return key === "error_category" ? plainLabel(value) : value;
    }

    function compare(before, after) {
        return `<div class="delta">
            <div class="text-block"><small>Previous</small>${escape(before) || "—"}</div>
            <div class="text-block"><small>Current</small>${escape(after) || "—"}</div>
        </div>`;
    }

    function annotationDiff(previous, current, title) {
        const before = previous?.errors[0] ?? {};
        const after = current.errors[0] ?? {};
        const changed = Object.entries(fieldNames).filter(([key]) => before[key] !== after[key]);
        if (!previous || !changed.length) return "";
        return `<details class="annotation-diff" open><summary>${title}</summary>${
            changed.map(([key, label]) => `<div class="diff-item"><h4>${label}</h4>${
                compare(fieldValue(key, before[key]), fieldValue(key, after[key]))
            }</div>`).join("")
        }</details>`;
    }

    function annotationFields(annotation) {
        const errors = annotation.errors.map((error) => `
            <dl class="annotation">${Object.entries(fieldNames).filter(([key]) => error[key]).map(([key, name]) => `
                <div><dt>${name}</dt><dd class="text-block">${escape(fieldValue(key, error[key]))}</dd></div>
            `).join("")}</dl>
        `).join("");
        return `<p class="judgment">${escape(plainLabel(annotation.judgment))}</p>${errors}`;
    }

    function stageContent(entry, previous) {
        const [title, , actor] = labels[entry.action];
        const annotation = entry.issued_annotation ?? entry.annotation;
        const annotationTitle = entry.issued_annotation ? "Issued benchmark annotation" :
            entry.action === "human_override" ? "Human annotation" : "Recorded annotation";
        const noteTitle = entry.note_translated ? "Reviewer feedback (English translation)" : "Original reviewer feedback";
        const note = entry.note ? `<details open class="note"><summary>${noteTitle}</summary>
            <p class="text-block">${escape(entry.note)}</p></details>` : "";
        const fieldFeedback = entry.field_feedback ? `<details open class="note"><summary>Recorded field feedback</summary>
            <dl class="annotation">${Object.entries(entry.field_feedback).map(([key, feedback]) =>
                `<div><dt>${fieldNames[key]}</dt><dd class="text-block">${escape(feedback)}</dd></div>`
            ).join("")}</dl></details>` : "";
        let candidateDiff = "";
        if (entry.action === "regenerated" && previous) {
            candidateDiff = previous.candidate !== entry.candidate
                ? `<details><summary>Compare candidates</summary>${compare(previous.candidate, entry.candidate)}</details>`
                : '<p class="subtle">This regeneration kept the candidate text unchanged.</p>';
        }
        const previousAnnotation = entry.issued_annotation ? entry.annotation : previous?.annotation;
        const diff = annotationDiff(previousAnnotation, annotation,
            entry.issued_annotation ? "Changes in the issued annotation" : "Changed annotation fields");
        return `<div class="step-content" id="stage-content">
            <div class="label-row"><h3>${title}</h3><span class="chip">${actor} · Candidate v${entry.candidate_version} · Annotation v${entry.annotation_version}</span></div>
            ${entry.issued_annotation ? '<p class="subtle">Accepted by a human reviewer. The candidate was matched to the issued dataset.</p>' : ""}
            ${note}${fieldFeedback}
            <div class="candidate"><h3>Candidate response</h3><p class="text-block">${escape(entry.candidate)}</p></div>
            ${candidateDiff}
            ${entry.action === "annotation_revised" ? '<p class="subtle">The candidate response stayed unchanged.</p>' : ""}
            ${diff}
            <details ${diff ? "" : "open"}><summary>${annotationTitle}</summary>${annotationFields(annotation)}</details>
        </div>`;
    }

    function renderStage() {
        const steps = cases[caseIndex].steps;
        const nav = el("#stage-navigation");
        nav.innerHTML = `<div class="stage-nav">
                <p aria-live="polite">Step ${stepIndex + 1} of ${steps.length} · ${labels[steps[stepIndex].action][0]}</p>
                <div class="actions">
                    <button class="button" type="button" id="previous" ${stepIndex === 0 ? "disabled" : ""}>Previous</button>
                    <button class="button primary" type="button" id="next" ${stepIndex + 1 === steps.length ? "disabled" : ""}>Next step</button>
                </div>
            </div>
            <ol class="stage-list" aria-label="Recorded steps">${steps.map((entry, index) => `
                <li><button class="button" type="button" data-step="${index}" ${index === stepIndex ? 'aria-current="step"' : ""}>
                    ${index + 1}. ${labels[entry.action][1]}</button></li>
            `).join("")}</ol>`;
        el("#step").innerHTML = stageContent(steps[stepIndex], steps[stepIndex - 1]);
        const showStep = (index, source) => {
            stepIndex = index;
            renderStage();
            const control = el(source);
            (control?.disabled ? el(`[data-step="${index}"]`) : control)?.focus();
        };
        el("#previous").onclick = () => showStep(stepIndex - 1, "#previous");
        el("#next").onclick = () => showStep(stepIndex + 1, "#next");
        nav.querySelectorAll("[data-step]").forEach((button) => {
            button.onclick = () => showStep(Number(button.dataset.step), `[data-step="${button.dataset.step}"]`);
        });
    }

    function renderCase() {
        const current = cases[caseIndex];
        el("#cases").innerHTML = cases.map((item, index) => `
            <button class="button case-button" type="button" data-case="${index}" aria-pressed="${caseIndex === index}">
                <small>${escape(item.subject)} · ${item.steps.length} steps</small>
                <strong>${escape(item.title)}</strong>
            </button>
        `).join("");
        const sourceAnswer = current.reference
            ? `<p class="text-block"><strong>Source answer:</strong> ${escape(current.reference)}</p>` : "";
        const route = current.category
            ? `Target ${escape(current.category)} · ${escape(plainLabel(current.target_error))}`
            : "Field-level revision";
        const sourceImage = current.image
            ? `<img class="source-image" src="${escape(current.image)}" alt="Original microscopy image with a 400 nanometer scale bar">`
            : "";
        el("#case").innerHTML = `<div class="section-head">
            <div><h2 id="case-heading">${escape(current.title)}</h2><p>${escape(current.focus)}</p></div>
            <span class="chip">${route}</span>
        </div>
        <div class="replay-body">
            <details class="source-box"><summary>Problem and reference · ${escape(current.source)}</summary>
                <p class="text-block">${escape(current.question)}</p>${sourceImage}${sourceAnswer}
                <p class="subtle">Source and model notation are preserved.</p>
            </details>
            <section class="review-stage" aria-label="Review playback">
                <div id="stage-navigation"></div><div id="step"></div>
            </section>
        </div>`;
        el("#cases").querySelectorAll("[data-case]").forEach((button) => {
            button.onclick = () => {
                caseIndex = Number(button.dataset.case);
                stepIndex = 0;
                renderCase();
                const title = el("#case-heading");
                title.tabIndex = -1;
                title.focus();
            };
        });
        renderStage();
    }

    async function load() {
        const notice = el("#replay-notice");
        try {
            const response = await fetch("/api/replays");
            if (response.status === 404) {
                notice.textContent = "This checkout has no local archive. Open the editable demo to try the workflow.";
                return;
            }
            if (!response.ok) throw new Error("Could not load the local archive.");
            ({cases} = await response.json());
            renderCase();
            el("#replay-layout").hidden = false;
            notice.hidden = true;
        } catch {
            notice.textContent = "Could not read the local review archive.";
        }
    }

    void load();
})();
