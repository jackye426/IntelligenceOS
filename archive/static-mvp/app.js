const STORAGE_KEY = "docmap.clinic-intel.accounts.v1";

const pipelineStages = [
  "Identified",
  "Researching",
  "Contact found",
  "Outreach drafted",
  "Contacted",
  "Replied",
  "Meeting booked",
  "Demo completed",
  "Proposal sent",
  "Won",
  "Lost",
  "Paused",
];

const seedAccounts = [
  {
    id: "acct-001",
    name: "Harbour Family Clinic",
    website: "https://harbourfamily.example",
    owner: "Yulon",
    stage: "Outreach drafted",
    nextAction: "Review draft with clinic-specific pricing evidence",
    due: "2026-07-01",
    fitScore: 82,
    contacts: [
      { name: "Dr. Amelia Tan", role: "Clinical Director", confidence: "High" },
      { name: "Front desk team", role: "Contact route", confidence: "Medium" },
    ],
    services: ["GP consultations", "Health screening", "Vaccinations"],
    locations: ["Tanjong Pagar"],
    pricing: ["Consultations from $45", "Screening packages listed"],
    observations: [
      {
        text: "Booking path is phone-first, with no online triage or appointment status messaging visible.",
        sourceId: "src-001",
      },
      {
        text: "Preventive screening pages are strong but lack a next-step comparison table.",
        sourceId: "src-002",
      },
    ],
    salesAngle:
      "Position DocMap as a lighter patient acquisition and conversion layer for screening and repeat GP visits.",
    draft: {
      approved: false,
      subject: "Improving booking conversion for Harbour Family Clinic",
      body:
        "Hi Dr. Tan,\n\nI noticed Harbour Family Clinic presents preventive screening clearly, but the booking route still appears phone-led. DocMap may be able to help turn those service pages into tracked patient enquiries while keeping your team in control of follow-up.\n\nWould it be useful to compare where patients drop off between service discovery and contacting reception?\n\nBest,\nDocMap",
    },
    sources: [
      {
        id: "src-001",
        title: "Contact page",
        url: "https://harbourfamily.example/contact",
        capturedAt: "2026-06-24",
        evidence: "Phone number and email are listed as primary routes. No online appointment form observed.",
      },
      {
        id: "src-002",
        title: "Health screening page",
        url: "https://harbourfamily.example/screening",
        capturedAt: "2026-06-24",
        evidence: "Screening packages and pricing ranges are visible; page ends with a generic contact prompt.",
      },
    ],
    interactions: [
      "2026-06-20: Imported meeting note from manual research.",
      "2026-06-24: Website evidence reviewed by owner.",
    ],
  },
  {
    id: "acct-002",
    name: "Northbridge Dental Studio",
    website: "https://northbridgedental.example",
    owner: "Internal team",
    stage: "Researching",
    nextAction: "Classify practitioner roles",
    due: "2026-06-30",
    fitScore: 68,
    contacts: [{ name: "Clinic manager", role: "Likely buyer", confidence: "Low" }],
    services: ["Dental implants", "Whitening", "Emergency dentistry"],
    locations: ["Bishan", "Novena"],
    pricing: ["Implant guide mentions consultation-first pricing"],
    observations: [
      {
        text: "Emergency dentistry has prominent demand intent but the contact route splits between two branches.",
        sourceId: "src-101",
      },
    ],
    salesAngle:
      "Focus on routing high-intent emergency and implant enquiries to the right branch.",
    draft: {
      approved: false,
      subject: "Routing high-intent dental enquiries by branch",
      body:
        "Hi,\n\nWe are looking at how patients move from service pages to the right clinic contact route. Northbridge Dental Studio appears to have strong intent around emergency and implant services, with branch choice as a key step.\n\nDocMap could help track and improve that handoff without changing your clinical workflow.\n\nBest,\nDocMap",
    },
    sources: [
      {
        id: "src-101",
        title: "Emergency dentistry page",
        url: "https://northbridgedental.example/emergency",
        capturedAt: "2026-06-25",
        evidence: "Page lists two branches and separate phone numbers near the call to action.",
      },
    ],
    interactions: ["2026-06-25: Initial website review queued."],
  },
  {
    id: "acct-003",
    name: "Orchard Skin & Laser",
    website: "https://orchardskin.example",
    owner: "Yulon",
    stage: "Contact found",
    nextAction: "Confirm whether medical director is the right contact",
    due: "2026-07-03",
    fitScore: 74,
    contacts: [{ name: "Dr. Rachel Lim", role: "Medical Director", confidence: "Medium" }],
    services: ["Acne care", "Pigmentation", "Laser treatments"],
    locations: ["Orchard"],
    pricing: ["No public pricing observed"],
    observations: [
      {
        text: "Service pages emphasize outcomes, but pricing and consultation expectations are not explicit.",
        sourceId: "src-201",
      },
    ],
    salesAngle:
      "Frame DocMap around consultation readiness and evidence-backed patient education.",
    draft: {
      approved: false,
      subject: "Helping patients choose the right skin consultation",
      body:
        "Hi Dr. Lim,\n\nYour service pages explain treatment categories well. One opportunity may be helping patients understand what to do next before they contact the clinic.\n\nDocMap can structure that discovery path and give your team clearer context before follow-up.\n\nBest,\nDocMap",
    },
    sources: [
      {
        id: "src-201",
        title: "Acne treatment page",
        url: "https://orchardskin.example/acne",
        capturedAt: "2026-06-26",
        evidence: "Treatment overview is detailed; no pricing or consultation preparation section is shown.",
      },
    ],
    interactions: ["2026-06-26: Contact route found on footer and about page."],
  },
];

let accounts = loadAccounts();
let selectedAccountId = accounts[0]?.id;

const viewTitle = document.querySelector("#viewTitle");
const views = {
  accounts: document.querySelector("#accountsView"),
  pipeline: document.querySelector("#pipelineView"),
  research: document.querySelector("#researchView"),
  outreach: document.querySelector("#outreachView"),
};

const accountList = document.querySelector("#accountList");
const accountDetail = document.querySelector("#accountDetail");
const pipelineBoard = document.querySelector("#pipelineBoard");
const evidenceLedger = document.querySelector("#evidenceLedger");
const evidenceCount = document.querySelector("#evidenceCount");
const claimChecks = document.querySelector("#claimChecks");
const claimStatus = document.querySelector("#claimStatus");
const draftSubject = document.querySelector("#draftSubject");
const draftBody = document.querySelector("#draftBody");
const searchInput = document.querySelector("#searchInput");
const accountDialog = document.querySelector("#accountDialog");
const accountForm = document.querySelector("#accountForm");
const researchForm = document.querySelector("#researchForm");

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

document.querySelector("#newAccountButton").addEventListener("click", () => {
  accountDialog.showModal();
});

document.querySelector("#exportButton").addEventListener("click", () => {
  const account = getSelectedAccount();
  const blob = new Blob([JSON.stringify(account, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${slugify(account.name)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});

document.querySelector("#runResearchButton").addEventListener("click", () => {
  const form = new FormData(researchForm);
  const name = form.get("clinicName")?.toString().trim();
  const website = form.get("website")?.toString().trim();
  if (!name || !website) {
    researchForm.reportValidity();
    return;
  }

  const id = `acct-${Date.now()}`;
  accounts.unshift({
    id,
    name,
    website,
    owner: "Internal team",
    stage: "Researching",
    nextAction: "Review captured source evidence",
    due: new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10),
    fitScore: 50,
    contacts: form.get("knownContact")
      ? [{ name: form.get("knownContact").toString(), role: "Unclassified", confidence: "Low" }]
      : [],
    services: [],
    locations: [],
    pricing: [],
    observations: [
      {
        text: form.get("notes")?.toString() || "Manual note added. Awaiting source-backed extraction.",
        sourceId: "manual-001",
      },
    ],
    salesAngle: "Pending human-reviewed research run.",
    draft: {
      approved: false,
      subject: `Research follow-up for ${name}`,
      body: "Draft pending source-backed review.",
    },
    sources: [
      {
        id: "manual-001",
        title: "Manual intake",
        url: website,
        capturedAt: new Date().toISOString().slice(0, 10),
        evidence: form.get("notes")?.toString() || "Clinic submitted for research.",
      },
    ],
    interactions: [`${new Date().toISOString().slice(0, 10)}: Research run queued manually.`],
  });
  selectedAccountId = id;
  saveAccounts();
  researchForm.reset();
  renderAll();
});

document.querySelector("#regenerateDraftButton").addEventListener("click", () => {
  const account = getSelectedAccount();
  account.draft.subject = `Patient journey opportunity for ${account.name}`;
  account.draft.body = generateDraft(account);
  account.draft.approved = false;
  saveAccounts();
  renderOutreach();
});

document.querySelector("#approveDraftButton").addEventListener("click", () => {
  const account = getSelectedAccount();
  account.draft.approved = true;
  if (account.stage === "Outreach drafted") {
    account.stage = "Contacted";
    account.interactions.unshift(`${new Date().toISOString().slice(0, 10)}: Draft approved by owner.`);
  }
  saveAccounts();
  renderAll();
});

document.querySelectorAll(".segmented button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    const account = getSelectedAccount();
    account.draft.body = generateDraft(account, button.dataset.tone);
    saveAccounts();
    renderOutreach();
  });
});

accountForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(accountForm);
  const name = form.get("name").toString().trim();
  const website = form.get("website").toString().trim();
  const owner = form.get("owner").toString().trim();
  const notes = form.get("notes").toString().trim();
  if (!name || !website || !owner) return;

  const id = `acct-${Date.now()}`;
  accounts.unshift({
    id,
    name,
    website,
    owner,
    stage: "Identified",
    nextAction: "Queue website research",
    due: new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10),
    fitScore: 40,
    contacts: [],
    services: [],
    locations: [],
    pricing: [],
    observations: notes ? [{ text: notes, sourceId: "manual-001" }] : [],
    salesAngle: "Pending research.",
    draft: {
      approved: false,
      subject: `Intro to ${name}`,
      body: "Draft pending source-backed review.",
    },
    sources: [
      {
        id: "manual-001",
        title: "Manual intake",
        url: website,
        capturedAt: new Date().toISOString().slice(0, 10),
        evidence: notes || "Clinic created manually.",
      },
    ],
    interactions: [`${new Date().toISOString().slice(0, 10)}: Account created.`],
  });
  selectedAccountId = id;
  saveAccounts();
  accountDialog.close();
  accountForm.reset();
  renderAll();
});

searchInput.addEventListener("input", renderAccountList);

function switchView(viewName) {
  Object.entries(views).forEach(([name, view]) => view.classList.toggle("active", name === viewName));
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewName);
  });
  viewTitle.textContent = titleCase(viewName);
  renderAll();
}

function renderAll() {
  renderAccountList();
  renderAccountDetail();
  renderPipeline();
  renderResearch();
  renderOutreach();
}

function renderAccountList() {
  const query = searchInput.value.trim().toLowerCase();
  const visible = accounts.filter((account) => account.name.toLowerCase().includes(query));
  accountList.innerHTML = visible
    .map(
      (account) => `
        <button class="account-card ${account.id === selectedAccountId ? "active" : ""}" data-account-id="${account.id}">
          <strong>${escapeHtml(account.name)}</strong>
          <span class="source-link">${escapeHtml(account.website)}</span>
          <span class="meta-row">
            <span class="stage-pill">${escapeHtml(account.stage)}</span>
            <span class="pill">Owner: ${escapeHtml(account.owner)}</span>
          </span>
        </button>
      `,
    )
    .join("");

  accountList.querySelectorAll(".account-card").forEach((card) => {
    card.addEventListener("click", () => {
      selectedAccountId = card.dataset.accountId;
      renderAll();
    });
  });
}

function renderAccountDetail() {
  const account = getSelectedAccount();
  accountDetail.innerHTML = `
    <div class="detail-hero">
      <div>
        <h2>${escapeHtml(account.name)}</h2>
        <a class="source-link" href="${escapeAttribute(account.website)}" target="_blank" rel="noreferrer">${escapeHtml(account.website)}</a>
        <div class="tag-row">
          <span class="stage-pill">${escapeHtml(account.stage)}</span>
          <span class="pill">Due ${escapeHtml(account.due)}</span>
          <span class="pill">${account.sources.length} sources</span>
        </div>
      </div>
      <div class="score" aria-label="Fit score">
        <span><strong>${account.fitScore}</strong>fit</span>
      </div>
    </div>
    <div class="detail-grid">
      ${sectionList("Contacts", account.contacts.map((contact) => `${contact.name} - ${contact.role} (${contact.confidence})`))}
      ${sectionList("Services", account.services)}
      ${sectionList("Locations", account.locations)}
      ${sectionList("Pricing", account.pricing)}
      <section class="section-box full">
        <h3>Patient Journey Observations</h3>
        <ul class="list">
          ${account.observations
            .map((observation) => {
              const source = account.sources.find((item) => item.id === observation.sourceId);
              return `<li>${escapeHtml(observation.text)}<br><a class="source-link" href="${escapeAttribute(source?.url || account.website)}" target="_blank" rel="noreferrer">${escapeHtml(source?.title || "Manual note")}</a></li>`;
            })
            .join("")}
        </ul>
      </section>
      <section class="section-box full">
        <h3>Likely DocMap Sales Angle</h3>
        <p>${escapeHtml(account.salesAngle)}</p>
      </section>
      <section class="section-box full">
        <h3>Activity</h3>
        <ul class="list">${account.interactions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </section>
    </div>
  `;
}

function renderPipeline() {
  const activeStages = pipelineStages.filter((stage) => accounts.some((account) => account.stage === stage));
  pipelineBoard.innerHTML = activeStages
    .map((stage) => {
      const stageAccounts = accounts.filter((account) => account.stage === stage);
      return `
        <section class="pipeline-column">
          <h2>${escapeHtml(stage)} <span class="pill">${stageAccounts.length}</span></h2>
          ${stageAccounts
            .map(
              (account) => `
                <article class="deal-card">
                  <strong>${escapeHtml(account.name)}</strong>
                  <span>${escapeHtml(account.nextAction)}</span>
                  <span class="meta-row">
                    <span class="pill">Owner: ${escapeHtml(account.owner)}</span>
                    <span class="pill">Due ${escapeHtml(account.due)}</span>
                  </span>
                </article>
              `,
            )
            .join("")}
        </section>
      `;
    })
    .join("");
}

function renderResearch() {
  const account = getSelectedAccount();
  evidenceCount.textContent = `${account.sources.length} sources`;
  evidenceLedger.innerHTML = account.sources
    .map(
      (source) => `
        <article class="evidence-item">
          <h3>${escapeHtml(source.title)}</h3>
          <p>${escapeHtml(source.evidence)}</p>
          <a class="source-link" href="${escapeAttribute(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.url)}</a>
          <div class="tag-row">
            <span class="pill">Captured ${escapeHtml(source.capturedAt)}</span>
            <span class="pill">Source ID ${escapeHtml(source.id)}</span>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderOutreach() {
  const account = getSelectedAccount();
  draftSubject.value = account.draft.subject;
  draftBody.value = account.draft.body;
  claimStatus.textContent = account.draft.approved ? "Approved" : "Needs review";
  claimChecks.innerHTML = [
    {
      text: "Every clinic-specific statement in the draft must map to a source or manual note.",
      state: account.sources.length ? "supported" : "needs-review",
    },
    {
      text: "No patient medical data is included in the outreach draft.",
      state: "supported",
    },
    {
      text: "No automated sending is enabled from this workspace.",
      state: "supported",
    },
  ]
    .map(
      (claim) => `
        <article class="claim-item" data-state="${claim.state}">
          <strong>${claim.state === "supported" ? "Supported" : "Needs review"}</strong>
          <p>${escapeHtml(claim.text)}</p>
        </article>
      `,
    )
    .join("");
}

draftSubject.addEventListener("input", () => {
  getSelectedAccount().draft.subject = draftSubject.value;
  getSelectedAccount().draft.approved = false;
  saveAccounts();
});

draftBody.addEventListener("input", () => {
  getSelectedAccount().draft.body = draftBody.value;
  getSelectedAccount().draft.approved = false;
  saveAccounts();
  renderOutreach();
});

function sectionList(title, items) {
  const listItems = items.length ? items : ["Pending research"];
  return `
    <section class="section-box">
      <h3>${escapeHtml(title)}</h3>
      <ul class="list">${listItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </section>
  `;
}

function generateDraft(account, tone = "direct") {
  const opener =
    tone === "warm"
      ? `Hi,\n\nI spent a little time reviewing ${account.name} and wanted to share one practical observation.`
      : tone === "brief"
        ? `Hi,\n\nQuick note after reviewing ${account.name}.`
        : `Hi,\n\nI reviewed ${account.name}'s public patient journey and noticed a concrete opportunity.`;
  const observation = account.observations[0]?.text || "There may be room to make the patient enquiry path clearer.";
  return `${opener}\n\n${observation}\n\nDocMap could help turn that path into clearer, tracked enquiries while keeping follow-up human reviewed.\n\nBest,\nDocMap`;
}

function getSelectedAccount() {
  return accounts.find((account) => account.id === selectedAccountId) || accounts[0];
}

function loadAccounts() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return Array.isArray(stored) && stored.length ? stored : seedAccounts;
  } catch {
    return seedAccounts;
  }
}

function saveAccounts() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts));
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

renderAll();
