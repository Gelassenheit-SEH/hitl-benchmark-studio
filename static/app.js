(function frontend() {
    "use strict";

    const el = (selector) => document.querySelector(selector);
    const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => (
        {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]
    ));
    const fieldNames = {
        error_span_or_step: "Error location",
        error_explanation: "Explanation",
        scientific_constraint: "Scientific constraint",
        minimal_repair: "Minimal repair",
        error_category: "Error category",
        error_subtype: "Subtype",
        applicability_conditions: "Applicability conditions",
    };
    const editable = Object.keys(fieldNames).slice(0, 4);
    const judgments = {
        clear_violation: "Clear violation",
        no_violation: "No violation",
        insufficient_evidence: "Insufficient evidence",
    };
    const actions = {
        reinject: "Regenerated candidate",
        revise: "Revised annotation",
        override: "Applied human override",
        release: "Released by reviewer",
        reject: "Rejected by reviewer",
    };
    const statusNames = {
        needs_review: "Needs review",
        released: "Released",
        rejected: "Rejected",
    };
    const messages = {
        reinject: "New candidate and annotation saved. The assigned category stayed the same.",
        revise: "New annotation saved. The candidate and unselected fields stayed the same.",
        override: "Human override saved as a new annotation version.",
        release: "Sample released by reviewer. The review record is ready to download.",
        reject: "Sample rejected. The decision is available in the review history.",
    };
    const presetReplyNotice = "This editable exercise uses preset model replies. Your feedback is saved. The reply text is fixed regardless of how you phrase your feedback.";
    let config;
    let batch;
    let plan;
    let preset = "balanced";
    let activeId;
    let openAction;
    let busy = false;

    const categoryName = (code) => `${code} · ${config.categories[code]}`;
    const activeSample = () => batch?.samples.find((sample) => sample.id === activeId) ?? batch?.samples[0];

    async function api(path, body) {
        const options = body === undefined ? {} : {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
        };
        const response = await fetch(`/api/${path}`, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        return data;
    }

    function notify(message, error = false) {
        const notice = el("#notice");
        notice.hidden = !message;
        notice.textContent = message;
        notice.classList.toggle("error", error);
        if (error) {
            notice.tabIndex = -1;
            notice.focus();
        }
    }

    function focusSection(selector) {
        const section = el(selector);
        section.scrollIntoView({block: "start"});
        const heading = section.querySelector("h2");
        heading.tabIndex = -1;
        heading.focus({preventScroll: true});
    }

    async function run(control, operation) {
        if (busy) return;
        busy = true;
        if (control) control.disabled = true;
        try {
            await operation();
        } catch (error) {
            notify(error.message, true);
        } finally {
            busy = false;
            if (control?.isConnected) control.disabled = false;
        }
    }

    async function loadPlan() {
        ({preview: plan} = await api("preview", {preset}));
    }

    function renderBatch() {
        const controls = el("#batch-controls");
        if (batch) {
            controls.innerHTML = `${escape(config.presets[batch.preset].label)}
                <button type="button" class="button" id="reset">Reset batch</button>`;
            el("#reset").onclick = ({currentTarget}) => run(currentTarget, async () => {
                await loadPlan();
                ({batch} = await api("reset", {}));
                activeId = undefined;
                openAction = undefined;
                render();
                notify("Batch reset. You can start again with the same or a different preset.");
                focusSection("#batch");
            });
        } else {
            controls.innerHTML = `<label class="preset-label" for="preset">Category allocation</label>
                <select id="preset">${Object.entries(config.presets).map(([value, {label}]) => `
                    <option value="${value}" ${value === preset ? "selected" : ""}>${escape(label)}</option>
                `).join("")}</select>
                <button type="button" class="button primary" id="generate">Generate batch</button>`;
            el("#preset").onchange = ({currentTarget}) => run(currentTarget, async () => {
                const oldPreset = preset;
                preset = currentTarget.value;
                el("#generate").disabled = true;
                try {
                    await loadPlan();
                } catch (error) {
                    preset = oldPreset;
                    throw error;
                } finally {
                    renderBatch();
                }
                el("#preset").focus();
            });
            el("#generate").onclick = ({currentTarget}) => run(currentTarget, async () => {
                ({batch} = await api("batch", {preset}));
                activeId = batch.samples[0].id;
                render();
                notify("Batch generated. Start with the cart example to try both review actions.");
                focusSection("#review");
            });
        }
        const counts = Object.keys(config.categories).map((code) => `
            <div class="count-card">
                <strong>${escape(categoryName(code))}</strong>
                <div class="count-stats">
                    <span>Planned <b>${(batch ?? plan).planned[code]}</b></span>
                    <span>Generated <b>${batch?.generated[code] ?? 0}</b></span>
                    <span>Released <b>${batch?.released[code] ?? 0}</b></span>
                </div>
            </div>`).join("");
        const list = (batch?.samples ?? plan.assignments).map((sample) => {
            const label = `<strong>${escape(sample.title)}</strong>
                <small>${escape(sample.subject)} · ${escape(sample.category)}${batch ? ` · ${statusNames[sample.status]}` : ""}</small>`;
            return batch
                ? `<button class="sample-link" type="button" data-sample="${escape(sample.id)}"
                    aria-pressed="${sample.id === activeSample()?.id}">${label}</button>`
                : `<div class="sample-preview">${label}</div>`;
        }).join("");
        el("#batch-table").innerHTML = `<div class="counts">${counts}</div><div class="sample-list">${list}</div>`;
        el("#batch-table").setAttribute("aria-busy", "false");
        el("#batch-table").querySelectorAll("[data-sample]").forEach((button) => {
            button.onclick = () => {
                if (busy) return;
                activeId = button.dataset.sample;
                openAction = undefined;
                render();
                notify("");
                focusSection("#review");
            };
        });
    }

    function guide(sample) {
        if (sample.id !== "PHY-01" || sample.status !== "needs_review") return "";
        let prompt;
        if (sample.candidates.length === 1 && !sample.review_history.length) {
            prompt = "Compare the speed in the candidate with E2. If the candidate changes an input as well as the time unit, send it back for regeneration.";
        } else if (sample.candidates.length === 2
            && sample.ai_preannotation.suggested_errors[0]?.minimal_repair === "Convert 1.5 min to 150 s.") {
            prompt = "The new candidate keeps the given speed. Check the proposed repair against E2 and request a revision to Minimal repair.";
        }
        return prompt ? `<p class="guide">${prompt}</p>` : "";
    }

    function renderReview(sample) {
        const candidate = sample.candidates.at(-1);
        const version = sample.ai_preannotation_versions.at(-1);
        const annotation = version.annotation;
        const error = annotation.suggested_errors[0];
        const evidence = Object.entries(sample.evidence).map(([key, text]) => `
            <li><b>${escape(key)}</b><span>${escape(text)}</span></li>`).join("");
        const fields = error ? Object.entries(fieldNames).map(([key, label]) => `
            <div><dt>${label}</dt><dd>${escape(error[key])}</dd></div>`).join("") : "";
        const labelMatches = error?.error_category === config.categories[sample.category];
        el("#review").className = "panel review";
        el("#review").innerHTML = `<div class="section-head">
                <div><h2 id="review-heading">${escape(sample.title)}</h2><p>${escape(sample.subject)} · ${escape(sample.id)} · ${statusNames[sample.status]}</p></div>
                <span class="chip">${escape(categoryName(sample.category))}</span>
            </div>
            <div class="review-grid">
                <div class="evidence">
                    <h3>Source evidence</h3>
                    <p class="question">${escape(sample.question)}</p>
                    <ul class="evidence-list">${evidence}</ul>
                    <div class="reference"><h3>Reference answer</h3><p>${escape(sample.reference)}</p></div>
                </div>
                <div class="workspace">
                    <div class="candidate">
                        <div class="label-row"><h3>Generated candidate</h3><span class="chip warning">Candidate v${candidate.version}</span></div>
                        <p>${escape(candidate.text)}</p>
                    </div>
                    <div class="label-row"><h3>${annotation.actor === "human" ? "Human annotation" : "Model annotation"}</h3>
                        <span class="chip">Annotation v${version.version}</span></div>
                    <p class="subtle">${judgments[annotation.suggested_judgment]}
                        ${labelMatches ? " · Category label matches assignment" : ""}</p>
                    ${fields ? `<dl class="annotation">${fields}</dl>` : ""}
                    ${guide(sample)}
                    ${sample.status === "needs_review" ? reviewButtons(sample, error) : `
                        <p class="guide">${sample.status === "released" ? "Released by the human reviewer." : "Rejected by the human reviewer."} See the decision in review history.</p>`}
                    <div id="form-slot"></div>
                </div>
            </div>`;
        el("#review").querySelectorAll("[data-action]").forEach((button) => {
            button.onclick = () => {
                if (busy) return;
                openAction = button.dataset.action;
                renderActionForm(sample);
                el("#form-slot input, #form-slot select, #form-slot textarea, #form-slot button[type=submit]")?.focus();
            };
        });
        renderActionForm(sample);
    }

    function reviewButtons(sample, error) {
        const canRegenerate = sample.candidates.length < 2;
        return `<div class="actions" aria-label="Review actions">
            <button class="button" type="button" data-action="reinject"${canRegenerate ? "" : ' disabled aria-describedby="regeneration-limit"'}>Send back for regeneration</button>
            ${error ? '<button class="button" type="button" data-action="revise">Request field revision</button>' : ""}
            <button class="button" type="button" data-action="override">Override annotation</button>
            <button class="button danger" type="button" data-action="reject">Reject sample</button>
            <button class="button primary" type="button" data-action="release">Review for release</button>
        </div>${canRegenerate ? "" : '<p class="subtle" id="regeneration-limit">This sample has used its one preset regeneration. Use Reset batch to try it again.</p>'}`;
    }

    function releaseReminders() {
        return `<ul class="release-reminders">${config.release_reminders.map((text) =>
            `<li>${escape(text)}</li>`).join("")}</ul>`;
    }

    function overrideFields(sample) {
        const annotation = sample.ai_preannotation;
        const error = annotation.suggested_errors[0] ??
            [...sample.ai_preannotation_versions].reverse().find((version) => version.annotation.suggested_errors[0])
                ?.annotation.suggested_errors[0] ?? {};
        const judgmentOptions = Object.entries(judgments).map(([value, label]) => `
            <option value="${value}">${label}</option>
        `).join("");
        const categoryOptions = Object.values(config.categories).map((label) => `
            <option value="${escape(label)}">${escape(label)}</option>
        `).join("");
        const fields = Object.entries(fieldNames).map(([key, label]) => `<label class="review-field"><span>${label}</span>
            ${key === "error_category" ? `<select name="override_${key}"><option value="">Keep current category</option>${categoryOptions}</select>`
                : `<textarea name="override_${key}" maxlength="1000" placeholder="${escape(error[key])}"></textarea>`}
            </label>`).join("");
        return `<label class="review-field"><span>Judgment</span><select name="judgment"><option value="">Keep current judgment</option>${judgmentOptions}</select></label>
            <fieldset id="override-fields" ${annotation.suggested_judgment === "clear_violation" ? "" : "hidden disabled"}>
                <legend>Annotation fields</legend>${fields}
            </fieldset>`;
    }

    function renderActionForm(sample) {
        const slot = el("#form-slot");
        if (!openAction || sample.status !== "needs_review") {
            slot.innerHTML = "";
            return;
        }
        const labels = {
            reinject: ["Why should the candidate be regenerated?", "Regenerate in same category"],
            revise: ["Give feedback on the fields the model may change.", "Apply selective revision"],
            override: ["Change only what needs correction.", "Save human override"],
            release: ["Before releasing this sample", "Release reviewed sample"],
            reject: ["Why should this sample be rejected?", "Confirm rejection"],
        };
        const [title, button] = labels[openAction];
        const note = `<label class="review-field"><span>Reason</span>
            <textarea name="note" maxlength="1000" required></textarea></label>`;
        const fields = {
            reinject: () => `<p class="guide">${presetReplyNotice}</p>${note}`,
            revise: () => `<p class="guide">${presetReplyNotice} The fields you fill in determine which parts of the reply are applied. Blank fields stay as they are.</p>${
                editable.map((key) => `<label class="review-field"><span>${fieldNames[key]}</span>
                    <textarea name="${key}" maxlength="1000"></textarea></label>`).join("")
            }`,
            override: () => '<p class="subtle">Leave any field blank to keep its current value.</p>' + overrideFields(sample),
            reject: () => note,
            release: releaseReminders,
        };
        slot.innerHTML = `<form class="action-form"><h3>${title}</h3>${fields[openAction]()}
            <div class="actions"><button class="button primary" type="submit">${button}</button>
                <button class="button" type="button" id="cancel-action">Cancel</button></div></form>`;
        slot.querySelector("#cancel-action").onclick = () => {
            if (busy) return;
            const buttonToRestore = el(`[data-action="${openAction}"]`);
            openAction = undefined;
            renderActionForm(sample);
            buttonToRestore.focus();
        };
        const form = slot.querySelector("form");
        if (openAction === "override") {
            form.elements.judgment.onchange = () => {
                const fieldset = slot.querySelector("#override-fields");
                const judgment = form.elements.judgment.value || sample.ai_preannotation.suggested_judgment;
                fieldset.disabled = fieldset.hidden = judgment !== "clear_violation";
            };
        }
        form.onsubmit = (event) => {
            event.preventDefault();
            const data = new FormData(form);
            const action = openAction;
            void run(event.submitter, async () => {
                const values = actionValues(action, data);
                ({batch} = await api("review", {
                    action, sample_id: sample.id, batch_id: batch.id,
                    version: sample.ai_preannotation_versions.at(-1).version, ...values,
                }));
                openAction = undefined;
                render();
                notify(messages[action]);
                focusSection(["revise", "release"].includes(action) ? "#record" : "#review");
            });
        };
    }

    function actionValues(action, data) {
        if (action === "release") {
            return {};
        }
        if (action === "revise") {
            return {instructions: Object.fromEntries(editable
                .map((key) => [key, data.get(key).trim()]).filter(([, text]) => text))};
        }
        if (action === "override") {
            const fields = Object.fromEntries(Object.keys(fieldNames).filter((key) => data.has(`override_${key}`))
                .map((key) => [key, data.get(`override_${key}`)]));
            return {judgment: data.get("judgment"), fields};
        }
        return {note: data.get("note")};
    }

    function contrast(before, after) {
        return `<div class="delta">
            <div><small>Previous</small>${escape(before)}</div>
            <div><small>Current</small>${escape(after)}</div>
        </div>`;
    }

    function renderEvent(sample, event) {
        let details = event.note ? `<p>${escape(event.note)}</p>` : "";
        if (event.action === "reinject") {
            details += contrast(sample.candidates[event.from_candidate_version - 1].text,
                sample.candidates[event.candidate_version - 1].text);
        }
        if (event.action === "revise") {
            const oldError = sample.ai_preannotation_versions[event.from_annotation_version - 1].annotation.suggested_errors[0];
            const newError = sample.ai_preannotation_versions[event.annotation_version - 1].annotation.suggested_errors[0];
            details += Object.entries(event.instructions).map(([key, instruction]) => `
                <p><strong>${fieldNames[key]}</strong> · ${escape(instruction)}</p>
                ${event.changed_fields.includes(key) ? contrast(oldError[key], newError[key]) : '<p>The prepared response kept this field unchanged.</p>'}
            `).join("");
            const preserved = editable.filter((key) => !Object.hasOwn(event.instructions, key)).map((key) => fieldNames[key]);
            if (preserved.length) details += `<p class="subtle">Held fixed · ${preserved.join(", ")}</p>`;
        }
        if (event.action === "release") {
            details += "<p>The reviewer accepted this candidate and annotation for release.</p>";
        }
        if (event.action === "override") {
            details += `<p>Human judgment · ${judgments[event.judgment]}</p>`;
        }
        return `<details open><summary>${actions[event.action]}
            <span> · Candidate v${event.candidate_version} · Annotation v${event.annotation_version}</span>
            </summary>${details}</details>`;
    }

    function renderTimeline(sample) {
        const released = Object.values(batch.released).some((count) => count > 0);
        el("#record").className = "panel timeline";
        el("#record").innerHTML = `<div class="section-head">
            <div><h2 id="history-heading">Review history</h2><p>${escape(sample.title)}</p></div>
            ${released ? '<a class="button primary" href="/api/reviewed.jsonl" download>Download reviewed JSONL</a>' : ""}
            </div><div class="timeline-body">
            <details><summary>Generated with assigned category <span> · Candidate v1 · Annotation v1</span></summary>
            <p>${escape(sample.candidates[0].text)}</p></details>
            ${sample.review_history.map((event) => renderEvent(sample, event)).join("")}
            </div>`;
    }

    function render() {
        renderBatch();
        const sample = activeSample();
        ["#review", "#record", "#review-link", "#export-link"].forEach((selector) => {
            el(selector).hidden = !sample;
        });
        if (sample) {
            renderReview(sample);
            renderTimeline(sample);
        }
    }

    void run(null, async () => {
        config = await api("session");
        el("#recorded-link").hidden = !config.has_recorded_cases;
        batch = config.batch;
        preset = batch?.preset ?? preset;
        await loadPlan();
        render();
    });
})();
