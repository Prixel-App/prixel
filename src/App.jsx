import React, { useState, useEffect, useCallback, useRef } from "react";
import { Plus, Trash2, Save, FilePlus2, Printer, FileDown, Copy, ChevronDown, ChevronUp, X, Check, Loader2, UploadCloud, DownloadCloud } from "lucide-react";
import { storage } from "./storage.js";

const STORAGE_KEY = "prixel-data";

const FONTS = `
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
`;

const COLOR_BARS = ["#F5F3EE", "#E8C24A", "#3ED598", "#29ABE2", "#FF4D2E", "#14161A"];

const emptyLine = () => ({
  id: Math.random().toString(36).slice(2, 9),
  description: "",
  unite: "forfait",
  qty: 1,
  price: 0,
});

const defaultProfile = {
  name: "Mon studio",
  tagline: "",
  address: "",
  phone: "",
  email: "",
  taxId: "",
  signatory: "",
  signatoryTitle: "",
};

const defaultDraft = (ref) => ({
  ref,
  docType: "Devis",
  date: new Date().toISOString().slice(0, 10),
  validity: "30 jours",
  clientName: "",
  clientStructure: "",
  clientType: "Privé",
  clientAddress: "",
  currency: "FCFA",
  tvaRate: 18,
  tvaExempt: false,
  lines: [emptyLine()],
  paymentTerms: "50% à la commande, solde à la livraison",
  notes: "",
});

function groupThousands(numStr) {
  return numStr.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function formatMoney(amount, currency) {
  if (currency === "EUR") {
    const fixed = amount.toFixed(2);
    const [intPart, decPart] = fixed.split(".");
    return groupThousands(intPart) + "," + decPart + " €";
  }
  return groupThousands(String(Math.round(amount))) + " FCFA";
}

function pad(n, len) {
  return String(n).padStart(len, "0");
}

export default function App() {
  const [profile, setProfile] = useState(defaultProfile);
  const [counter, setCounter] = useState(0);
  const [documents, setDocuments] = useState([]);
  const [draft, setDraft] = useState(defaultDraft("PRX-2026-001"));
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved
  const [showProfile, setShowProfile] = useState(false);
  const [showList, setShowList] = useState(false);
  const [importState, setImportState] = useState("idle");
  const fileInputRef = useRef(null);
  const [error, setError] = useState("");

  // Load state
  useEffect(() => {
    (async () => {
      try {
        const res = await storage.get(STORAGE_KEY);
        if (res && res.value) {
          const parsed = JSON.parse(res.value);
          setProfile(parsed.profile || defaultProfile);
          setCounter(parsed.counter || 0);
          setDocuments(parsed.documents || []);
          const nextRef = `PRX-${new Date().getFullYear()}-${pad((parsed.counter || 0) + 1, 3)}`;
          setDraft(defaultDraft(nextRef));
        } else {
          setDraft(defaultDraft(`PRX-${new Date().getFullYear()}-001`));
        }
      } catch (e) {
        setDraft(defaultDraft(`PRX-${new Date().getFullYear()}-001`));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const persist = useCallback(async (nextProfile, nextCounter, nextDocuments) => {
    try {
      await storage.set(
        STORAGE_KEY,
        JSON.stringify({ profile: nextProfile, counter: nextCounter, documents: nextDocuments })
      );
      return true;
    } catch (e) {
      setError("Échec de la sauvegarde. Réessaie.");
      return false;
    }
  }, []);

  const totals = (() => {
    const subtotal = draft.lines.reduce((s, l) => s + (Number(l.qty) || 0) * (Number(l.price) || 0), 0);
    const rate = draft.tvaExempt ? 0 : Number(draft.tvaRate) || 0;
    const tva = subtotal * (rate / 100);
    return { subtotal, tva, total: subtotal + tva, rate };
  })();

  function updateLine(id, field, value) {
    setDraft((d) => ({
      ...d,
      lines: d.lines.map((l) => (l.id === id ? { ...l, [field]: value } : l)),
    }));
  }

  function addLine() {
    setDraft((d) => ({ ...d, lines: [...d.lines, emptyLine()] }));
  }

  function removeLine(id) {
    setDraft((d) => ({ ...d, lines: d.lines.length > 1 ? d.lines.filter((l) => l.id !== id) : d.lines }));
  }

  async function handleSave() {
    setSaveState("saving");
    const isNewRef = !documents.some((doc) => doc.ref === draft.ref);
    const nextCounter = isNewRef ? counter + 1 : counter;
    const record = { ...draft, total: totals.total, savedAt: new Date().toISOString() };
    const nextDocuments = [
      record,
      ...documents.filter((doc) => doc.ref !== draft.ref),
    ].sort((a, b) => (a.ref < b.ref ? 1 : -1));

    const ok = await persist(profile, nextCounter, nextDocuments);
    if (ok) {
      setCounter(nextCounter);
      setDocuments(nextDocuments);
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 1800);
    } else {
      setSaveState("idle");
    }
  }

  async function handleSaveProfile(nextProfile) {
    setProfile(nextProfile);
    await persist(nextProfile, counter, documents);
  }

  function handleNew() {
    const nextRef = `PRX-${new Date().getFullYear()}-${pad(counter + 1, 3)}`;
    setDraft(defaultDraft(nextRef));
  }

  function handleDuplicate() {
    const nextRef = `PRX-${new Date().getFullYear()}-${pad(counter + 1, 3)}`;
    setDraft((d) => ({ ...d, ref: nextRef, date: new Date().toISOString().slice(0, 10) }));
  }

  function loadDocument(doc) {
    setDraft(doc);
    setShowList(false);
  }

  async function deleteDocument(ref) {
    const nextDocuments = documents.filter((d) => d.ref !== ref);
    const ok = await persist(profile, counter, nextDocuments);
    if (ok) setDocuments(nextDocuments);
  }

  function handlePrint() {
    window.print();
  }

  function handleWordExport() {
    const rowsHtml = draft.lines
      .map(
        (l) => `<tr>
          <td style="padding:8px;border-bottom:1px solid #ddd;">${escapeHtml(l.description || "—")}</td>
          <td style="padding:8px;border-bottom:1px solid #ddd;text-align:center;">${l.qty} ${escapeHtml(l.unite)}</td>
          <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right;">${formatMoney(Number(l.price) || 0, draft.currency)}</td>
          <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right;">${formatMoney((Number(l.qty) || 0) * (Number(l.price) || 0), draft.currency)}</td>
        </tr>`
      )
      .join("");

    const html = `
    <html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
    <head><meta charset="utf-8"><title>${draft.ref}</title></head>
    <body style="font-family:Calibri,Arial,sans-serif;color:#1a1a1a;">
      <table width="100%"><tr>
        <td>
          <div style="font-size:20px;font-weight:bold;letter-spacing:1px;">${escapeHtml(profile.name)}</div>
          <div style="font-size:12px;color:#555;">${escapeHtml(profile.tagline)}</div>
          <div style="font-size:11px;color:#777;margin-top:4px;">${escapeHtml(profile.address)}${profile.phone ? " · " + escapeHtml(profile.phone) : ""}${profile.email ? " · " + escapeHtml(profile.email) : ""}</div>
        </td>
        <td style="text-align:right;">
          <div style="font-size:18px;font-weight:bold;">${draft.docType.toUpperCase()}</div>
          <div style="font-family:'Courier New',monospace;font-size:13px;">${draft.ref}</div>
          <div style="font-size:12px;color:#555;">Date : ${formatDate(draft.date)}</div>
          ${draft.docType === "Devis" ? `<div style="font-size:12px;color:#555;">Validité : ${escapeHtml(draft.validity)}</div>` : ""}
        </td>
      </tr></table>
      <hr style="margin:16px 0;border:none;border-top:2px solid #1a1a1a;">
      <div style="margin-bottom:16px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;">Destinataire</div>
        <div style="font-size:14px;font-weight:bold;">${escapeHtml(draft.clientName || "—")}</div>
        <div style="font-size:12px;">${escapeHtml(draft.clientStructure)}</div>
        <div style="font-size:12px;color:#555;">${escapeHtml(draft.clientAddress)}</div>
      </div>
      <table width="100%" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f2f2f2;">
          <th style="text-align:left;padding:8px;">Description</th>
          <th style="text-align:center;padding:8px;">Qté</th>
          <th style="text-align:right;padding:8px;">Prix unitaire</th>
          <th style="text-align:right;padding:8px;">Total</th>
        </tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <table width="100%" style="margin-top:12px;font-size:13px;">
        <tr><td></td><td style="text-align:right;padding:4px;">Sous-total</td><td style="text-align:right;padding:4px;width:140px;">${formatMoney(totals.subtotal, draft.currency)}</td></tr>
        <tr><td></td><td style="text-align:right;padding:4px;">TVA (${draft.tvaExempt ? "Exonérée" : totals.rate + "%"})</td><td style="text-align:right;padding:4px;">${formatMoney(totals.tva, draft.currency)}</td></tr>
        <tr><td></td><td style="text-align:right;padding:6px;font-weight:bold;font-size:15px;border-top:2px solid #1a1a1a;">Total</td><td style="text-align:right;padding:6px;font-weight:bold;font-size:15px;border-top:2px solid #1a1a1a;">${formatMoney(totals.total, draft.currency)}</td></tr>
      </table>
      ${draft.tvaExempt ? '<div style="font-size:11px;color:#777;margin-top:6px;">Exonération de TVA — marché public.</div>' : ""}
      <div style="margin-top:20px;font-size:12px;">
        <div style="font-weight:bold;">Conditions de paiement</div>
        <div style="color:#555;">${escapeHtml(draft.paymentTerms)}</div>
      </div>
      ${draft.notes ? `<div style="margin-top:12px;font-size:12px;"><div style="font-weight:bold;">Notes</div><div style="color:#555;">${escapeHtml(draft.notes)}</div></div>` : ""}
      <table width="100%" style="margin-top:40px;"><tr>
        <td style="font-size:12px;">
          <div>${escapeHtml(profile.signatory)}</div>
          <div style="color:#777;">${escapeHtml(profile.signatoryTitle)}</div>
        </td>
      </tr></table>
    </body></html>`;

    const blob = new Blob(["\ufeff", html], { type: "application/msword;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${draft.ref}-${draft.docType}.doc`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleExportData() {
    const payload = JSON.stringify({ profile, counter, documents }, null, 2);
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kn-sauvegarde-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleImportClick() {
    fileInputRef.current?.click();
  }

  async function handleImportFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      if (!parsed || !Array.isArray(parsed.documents)) {
        throw new Error("Format de fichier inattendu.");
      }
      const nextProfile = parsed.profile || profile;
      const nextCounter = parsed.counter || counter;
      const existingRefs = new Set(documents.map((d) => d.ref));
      const merged = [
        ...documents,
        ...parsed.documents.filter((d) => !existingRefs.has(d.ref)),
      ].sort((a, b) => (a.ref < b.ref ? 1 : -1));

      const ok = await persist(nextProfile, nextCounter, merged);
      if (ok) {
        setProfile(nextProfile);
        setCounter(nextCounter);
        setDocuments(merged);
        setImportState("done");
        setTimeout(() => setImportState("idle"), 2000);
      }
    } catch (err) {
      setError("Fichier de sauvegarde illisible ou invalide.");
    }
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function formatDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 300, color: "#888", fontFamily: "Inter, sans-serif" }}>
        <Loader2 size={20} style={{ marginRight: 8, animation: "spin 1s linear infinite" }} />
        Chargement…
      </div>
    );
  }

  return (
    <div className="kn-app">
      <style>{`
        ${FONTS}
        @keyframes spin { to { transform: rotate(360deg); } }
        .kn-app {
          --ink: #14161A;
          --panel: #1C1F25;
          --panel-2: #23262D;
          --border: #33373F;
          --text: #E8E6E1;
          --text-dim: #9CA0A8;
          --accent: #FF4D2E;
          --accent-2: #3ED598;
          --paper: #FAFAF8;
          font-family: 'Inter', sans-serif;
          background: var(--ink);
          color: var(--text);
          border-radius: 12px;
          overflow: hidden;
          display: grid;
          grid-template-columns: minmax(340px, 440px) 1fr;
          min-height: 640px;
        }
        @media (max-width: 860px) {
          .kn-app { grid-template-columns: 1fr; }
        }
        .kn-console {
          padding: 20px;
          border-right: 1px solid var(--border);
          overflow-y: auto;
          max-height: 900px;
        }
        .kn-topbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 18px;
        }
        .kn-brand {
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          font-size: 13px;
          color: var(--text-dim);
        }
        .kn-ref {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          color: var(--accent-2);
        }
        .kn-toggle-group {
          display: flex;
          background: var(--panel-2);
          border-radius: 8px;
          padding: 3px;
          gap: 3px;
          margin-bottom: 16px;
        }
        .kn-toggle {
          flex: 1;
          border: none;
          background: transparent;
          color: var(--text-dim);
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          font-size: 12.5px;
          padding: 8px 10px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .kn-toggle.active {
          background: var(--accent);
          color: #14161A;
        }
        .kn-section {
          margin-bottom: 14px;
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
          background: var(--panel);
        }
        .kn-section-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          cursor: pointer;
          user-select: none;
        }
        .kn-section-title {
          font-family: 'Barlow Condensed', sans-serif;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-size: 12.5px;
          color: var(--text-dim);
          font-weight: 600;
        }
        .kn-section-body {
          padding: 4px 14px 14px 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .kn-field label {
          display: block;
          font-size: 11px;
          color: var(--text-dim);
          margin-bottom: 4px;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }
        .kn-field input, .kn-field select, .kn-field textarea {
          width: 100%;
          background: var(--panel-2);
          border: 1px solid var(--border);
          border-radius: 6px;
          color: var(--text);
          padding: 8px 10px;
          font-family: 'Inter', sans-serif;
          font-size: 13px;
          box-sizing: border-box;
        }
        .kn-field textarea { resize: vertical; min-height: 50px; }
        .kn-field input:focus, .kn-field select:focus, .kn-field textarea:focus {
          outline: 2px solid var(--accent-2);
          outline-offset: 0px;
        }
        .kn-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .kn-line {
          display: grid;
          grid-template-columns: 1fr 60px 90px 26px;
          gap: 6px;
          align-items: center;
          margin-bottom: 6px;
        }
        .kn-line input {
          background: var(--panel-2);
          border: 1px solid var(--border);
          border-radius: 6px;
          color: var(--text);
          padding: 7px 8px;
          font-size: 12.5px;
          font-family: 'Inter', sans-serif;
          width: 100%;
          box-sizing: border-box;
        }
        .kn-line-remove {
          background: transparent;
          border: none;
          color: var(--text-dim);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .kn-line-remove:hover { color: var(--accent); }
        .kn-add-line {
          display: flex;
          align-items: center;
          gap: 6px;
          background: transparent;
          border: 1px dashed var(--border);
          color: var(--text-dim);
          padding: 8px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 12.5px;
          justify-content: center;
          font-family: 'Inter', sans-serif;
        }
        .kn-add-line:hover { color: var(--accent-2); border-color: var(--accent-2); }
        .kn-checkbox {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12.5px;
          color: var(--text-dim);
        }
        .kn-actions {
          display: flex;
          gap: 8px;
          margin-top: 16px;
          flex-wrap: wrap;
        }
        .kn-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          border: 1px solid var(--border);
          background: var(--panel-2);
          color: var(--text);
          padding: 9px 12px;
          border-radius: 7px;
          cursor: pointer;
          font-size: 12.5px;
          font-family: 'Inter', sans-serif;
          font-weight: 500;
        }
        .kn-btn:hover { border-color: var(--accent-2); }
        .kn-btn.primary {
          background: var(--accent);
          border-color: var(--accent);
          color: #14161A;
          font-weight: 600;
        }
        .kn-btn.primary:hover { filter: brightness(1.08); }
        .kn-list {
          margin-top: 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 240px;
          overflow-y: auto;
        }
        .kn-list-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 10px;
          background: var(--panel-2);
          border-radius: 6px;
          font-size: 12px;
          cursor: pointer;
        }
        .kn-list-item:hover { outline: 1px solid var(--accent-2); }
        .kn-list-empty {
          color: var(--text-dim);
          font-size: 12px;
          padding: 8px;
        }
        .kn-hint {
          color: var(--text-dim);
          font-size: 11.5px;
          line-height: 1.5;
          margin-bottom: 4px;
        }
        .kn-doc-wrap {
          background: #0F1114;
          padding: 32px;
          overflow-y: auto;
          max-height: 900px;
          display: flex;
          justify-content: center;
        }
        .kn-paper {
          background: var(--paper);
          color: #1A1A1A;
          width: 100%;
          max-width: 640px;
          padding: 40px 44px;
          border-radius: 3px;
          box-shadow: 0 12px 40px rgba(0,0,0,0.45);
          font-family: 'Inter', sans-serif;
          box-sizing: border-box;
        }
        .kn-bars { display: flex; height: 5px; margin: 14px 0 22px 0; border-radius: 2px; overflow: hidden; }
        .kn-bars div { flex: 1; }
        .kn-doc-head {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
        }
        .kn-doc-name {
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 700;
          font-size: 22px;
          letter-spacing: 0.02em;
        }
        .kn-doc-tagline { font-size: 11.5px; color: #666; margin-top: 2px; }
        .kn-doc-meta { font-size: 11px; color: #888; margin-top: 6px; line-height: 1.5; }
        .kn-doc-type {
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          font-size: 18px;
          text-align: right;
        }
        .kn-doc-ref {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 13px;
          text-align: right;
          color: #333;
          margin-top: 2px;
        }
        .kn-doc-date { font-size: 11.5px; color: #777; text-align: right; margin-top: 4px; }
        .kn-hr { border: none; border-top: 2px solid #1A1A1A; margin: 18px 0 16px 0; }
        .kn-eyebrow { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; color: #999; margin-bottom: 3px; }
        .kn-client-name { font-size: 14px; font-weight: 700; }
        .kn-client-sub { font-size: 12px; color: #555; }
        .kn-table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 12.5px; }
        .kn-table th { text-align: left; padding: 8px 6px; background: #F0EFEB; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; color: #666; }
        .kn-table td { padding: 9px 6px; border-bottom: 1px solid #E7E5E0; vertical-align: top; }
        .kn-totals { margin-top: 10px; margin-left: auto; width: 260px; font-size: 12.5px; }
        .kn-totals-row { display: flex; justify-content: space-between; padding: 5px 0; color: #555; }
        .kn-totals-row.final { border-top: 2px solid #1A1A1A; margin-top: 4px; padding-top: 8px; font-weight: 700; font-size: 15px; color: #1A1A1A; }
        .kn-footnote { font-size: 11px; color: #888; margin-top: 6px; }
        .kn-block { margin-top: 22px; font-size: 12px; }
        .kn-block-title { font-weight: 700; margin-bottom: 2px; }
        .kn-block-body { color: #555; white-space: pre-wrap; }
        .kn-sign { margin-top: 44px; font-size: 12px; }
        .kn-sign-name { font-weight: 600; }
        .kn-sign-title { color: #888; }
        .kn-save-flag { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--accent-2); }
        .kn-error { color: var(--accent); font-size: 12px; margin-top: 8px; }
        @media print {
          @page { margin: 14mm; }
          html, body { background: #ffffff !important; }
          body * { visibility: hidden; }
          .kn-paper, .kn-paper * { visibility: visible; }
          .kn-paper { position: absolute; top: 0; left: 0; box-shadow: none; width: 100%; max-width: none; }
          .kn-doc-wrap { padding: 0; background: white; }
        }
      `}</style>

      <div className="kn-console no-print">
        <div className="kn-topbar">
          <div>
            <div className="kn-brand">Prixel — Devis / Facture</div>
            <div className="kn-ref">{draft.ref}</div>
          </div>
          {saveState === "saved" && (
            <div className="kn-save-flag"><Check size={14} /> Enregistré</div>
          )}
        </div>

        <div className="kn-toggle-group">
          <button className={`kn-toggle ${draft.docType === "Devis" ? "active" : ""}`} onClick={() => setDraft((d) => ({ ...d, docType: "Devis" }))}>Devis</button>
          <button className={`kn-toggle ${draft.docType === "Facture" ? "active" : ""}`} onClick={() => setDraft((d) => ({ ...d, docType: "Facture" }))}>Facture</button>
        </div>

        <div className="kn-section">
          <div className="kn-section-head" onClick={() => setShowProfile((s) => !s)}>
            <span className="kn-section-title">Émetteur</span>
            {showProfile ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
          {showProfile && (
            <div className="kn-section-body">
              <div className="kn-field">
                <label>Nom / raison sociale</label>
                <input value={profile.name} onChange={(e) => handleSaveProfile({ ...profile, name: e.target.value })} />
              </div>
              <div className="kn-field">
                <label>Activité</label>
                <input value={profile.tagline} onChange={(e) => handleSaveProfile({ ...profile, tagline: e.target.value })} />
              </div>
              <div className="kn-field">
                <label>Adresse</label>
                <input value={profile.address} onChange={(e) => handleSaveProfile({ ...profile, address: e.target.value })} />
              </div>
              <div className="kn-row2">
                <div className="kn-field">
                  <label>Téléphone</label>
                  <input value={profile.phone} onChange={(e) => handleSaveProfile({ ...profile, phone: e.target.value })} />
                </div>
                <div className="kn-field">
                  <label>Email</label>
                  <input value={profile.email} onChange={(e) => handleSaveProfile({ ...profile, email: e.target.value })} />
                </div>
              </div>
              <div className="kn-row2">
                <div className="kn-field">
                  <label>RCCM / N° contribuable</label>
                  <input value={profile.taxId} onChange={(e) => handleSaveProfile({ ...profile, taxId: e.target.value })} />
                </div>
                <div className="kn-field">
                  <label>Signataire</label>
                  <input value={profile.signatory} onChange={(e) => handleSaveProfile({ ...profile, signatory: e.target.value })} />
                </div>
              </div>
              <div className="kn-field">
                <label>Fonction du signataire</label>
                <input value={profile.signatoryTitle} onChange={(e) => handleSaveProfile({ ...profile, signatoryTitle: e.target.value })} />
              </div>
            </div>
          )}
        </div>

        <div className="kn-section">
          <div className="kn-section-head"><span className="kn-section-title">Client</span></div>
          <div className="kn-section-body">
            <div className="kn-field">
              <label>Nom du contact</label>
              <input value={draft.clientName} onChange={(e) => setDraft((d) => ({ ...d, clientName: e.target.value }))} />
            </div>
            <div className="kn-field">
              <label>Structure</label>
              <input value={draft.clientStructure} onChange={(e) => setDraft((d) => ({ ...d, clientStructure: e.target.value }))} />
            </div>
            <div className="kn-row2">
              <div className="kn-field">
                <label>Type</label>
                <select value={draft.clientType} onChange={(e) => setDraft((d) => ({ ...d, clientType: e.target.value }))}>
                  <option>Ministère</option>
                  <option>Institution publique</option>
                  <option>Privé</option>
                  <option>ONG</option>
                  <option>Corporate</option>
                </select>
              </div>
              <div className="kn-field">
                <label>Devise</label>
                <select value={draft.currency} onChange={(e) => setDraft((d) => ({ ...d, currency: e.target.value }))}>
                  <option value="FCFA">FCFA</option>
                  <option value="EUR">EUR</option>
                </select>
              </div>
            </div>
            <div className="kn-field">
              <label>Adresse</label>
              <input value={draft.clientAddress} onChange={(e) => setDraft((d) => ({ ...d, clientAddress: e.target.value }))} />
            </div>
          </div>
        </div>

        <div className="kn-section">
          <div className="kn-section-head"><span className="kn-section-title">Prestations</span></div>
          <div className="kn-section-body">
            {draft.lines.map((l) => (
              <div className="kn-line" key={l.id}>
                <input placeholder="Description" value={l.description} onChange={(e) => updateLine(l.id, "description", e.target.value)} />
                <input placeholder="Qté" type="number" value={l.qty} onChange={(e) => updateLine(l.id, "qty", e.target.value)} />
                <input placeholder="Prix unit." type="number" value={l.price} onChange={(e) => updateLine(l.id, "price", e.target.value)} />
                <button className="kn-line-remove" onClick={() => removeLine(l.id)} aria-label="Supprimer la ligne"><X size={15} /></button>
              </div>
            ))}
            <button className="kn-add-line" onClick={addLine}><Plus size={14} /> Ajouter une ligne</button>
          </div>
        </div>

        <div className="kn-section">
          <div className="kn-section-head"><span className="kn-section-title">Conditions</span></div>
          <div className="kn-section-body">
            <div className="kn-row2">
              <div className="kn-field">
                <label>TVA (%)</label>
                <input type="number" value={draft.tvaRate} disabled={draft.tvaExempt} onChange={(e) => setDraft((d) => ({ ...d, tvaRate: e.target.value }))} />
              </div>
              {draft.docType === "Devis" && (
                <div className="kn-field">
                  <label>Validité</label>
                  <input value={draft.validity} onChange={(e) => setDraft((d) => ({ ...d, validity: e.target.value }))} />
                </div>
              )}
            </div>
            <label className="kn-checkbox">
              <input type="checkbox" checked={draft.tvaExempt} onChange={(e) => setDraft((d) => ({ ...d, tvaExempt: e.target.checked }))} style={{ width: "auto" }} />
              Exonération de TVA (marché public)
            </label>
            <div className="kn-field">
              <label>Conditions de paiement</label>
              <textarea value={draft.paymentTerms} onChange={(e) => setDraft((d) => ({ ...d, paymentTerms: e.target.value }))} />
            </div>
            <div className="kn-field">
              <label>Notes</label>
              <textarea value={draft.notes} onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} />
            </div>
          </div>
        </div>

        {error && <div className="kn-error">{error}</div>}

        <div className="kn-actions">
          <button className="kn-btn primary" onClick={handleSave}>
            {saveState === "saving" ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Save size={14} />} Enregistrer
          </button>
          <button className="kn-btn" onClick={handleNew}><FilePlus2 size={14} /> Nouveau</button>
          <button className="kn-btn" onClick={handleDuplicate}><Copy size={14} /> Dupliquer</button>
          <button className="kn-btn" onClick={handlePrint}><Printer size={14} /> PDF</button>
          <button className="kn-btn" onClick={handleWordExport}><FileDown size={14} /> Word</button>
        </div>

        <div className="kn-section" style={{ marginTop: 14 }}>
          <div className="kn-section-head" onClick={() => setShowList((s) => !s)}>
            <span className="kn-section-title">Historique ({documents.length})</span>
            {showList ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
          {showList && (
            <div className="kn-section-body">
              {documents.length === 0 && <div className="kn-list-empty">Aucun document enregistré pour l'instant.</div>}
              <div className="kn-list">
                {documents.map((doc) => (
                  <div className="kn-list-item" key={doc.ref} onClick={() => loadDocument(doc)}>
                    <span>{doc.ref} · {doc.docType} · {doc.clientStructure || doc.clientName || "—"}</span>
                    <button className="kn-line-remove" onClick={(e) => { e.stopPropagation(); deleteDocument(doc.ref); }} aria-label="Supprimer"><Trash2 size={13} /></button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="kn-section">
          <div className="kn-section-head"><span className="kn-section-title">Sauvegarde</span></div>
          <div className="kn-section-body">
            <div className="kn-hint">
              Tes données restent uniquement sur cet appareil, dans ce navigateur. Exporte une sauvegarde régulièrement, ou pour la transférer vers un autre ordinateur.
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="kn-btn" style={{ flex: 1 }} onClick={handleExportData}>
                <DownloadCloud size={14} /> Exporter
              </button>
              <button className="kn-btn" style={{ flex: 1 }} onClick={handleImportClick}>
                {importState === "done" ? <Check size={14} /> : <UploadCloud size={14} />} Importer
              </button>
            </div>
            <input ref={fileInputRef} type="file" accept="application/json" style={{ display: "none" }} onChange={handleImportFile} />
          </div>
        </div>
      </div>

      <div className="kn-doc-wrap">
        <div className="kn-paper">
          <div className="kn-doc-head">
            <div>
              <div className="kn-doc-name">{profile.name}</div>
              <div className="kn-doc-tagline">{profile.tagline}</div>
              <div className="kn-doc-meta">
                {profile.address}<br />
                {[profile.phone, profile.email].filter(Boolean).join(" · ")}
                {profile.taxId && <><br />{profile.taxId}</>}
              </div>
            </div>
            <div>
              <div className="kn-doc-type">{draft.docType}</div>
              <div className="kn-doc-ref">{draft.ref}</div>
              <div className="kn-doc-date">
                Date : {formatDate(draft.date)}
                {draft.docType === "Devis" && <><br />Validité : {draft.validity}</>}
              </div>
            </div>
          </div>

          <div className="kn-bars">
            {COLOR_BARS.map((c, i) => <div key={i} style={{ background: c }} />)}
          </div>

          <div className="kn-eyebrow">Destinataire</div>
          <div className="kn-client-name">{draft.clientName || "—"}</div>
          {draft.clientStructure && <div className="kn-client-sub">{draft.clientStructure}</div>}
          {draft.clientAddress && <div className="kn-client-sub">{draft.clientAddress}</div>}

          <table className="kn-table">
            <thead>
              <tr>
                <th>Description</th>
                <th style={{ textAlign: "center" }}>Qté</th>
                <th style={{ textAlign: "right" }}>Prix unitaire</th>
                <th style={{ textAlign: "right" }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {draft.lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.description || "—"}</td>
                  <td style={{ textAlign: "center" }}>{l.qty} {l.unite}</td>
                  <td style={{ textAlign: "right" }}>{formatMoney(Number(l.price) || 0, draft.currency)}</td>
                  <td style={{ textAlign: "right" }}>{formatMoney((Number(l.qty) || 0) * (Number(l.price) || 0), draft.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="kn-totals">
            <div className="kn-totals-row"><span>Sous-total</span><span>{formatMoney(totals.subtotal, draft.currency)}</span></div>
            <div className="kn-totals-row"><span>TVA ({draft.tvaExempt ? "Exonérée" : `${totals.rate}%`})</span><span>{formatMoney(totals.tva, draft.currency)}</span></div>
            <div className="kn-totals-row final"><span>Total</span><span>{formatMoney(totals.total, draft.currency)}</span></div>
          </div>
          {draft.tvaExempt && <div className="kn-footnote" style={{ textAlign: "right" }}>Exonération de TVA — marché public.</div>}

          <div className="kn-block">
            <div className="kn-block-title">Conditions de paiement</div>
            <div className="kn-block-body">{draft.paymentTerms}</div>
          </div>
          {draft.notes && (
            <div className="kn-block">
              <div className="kn-block-title">Notes</div>
              <div className="kn-block-body">{draft.notes}</div>
            </div>
          )}

          <div className="kn-sign">
            <div className="kn-sign-name">{profile.signatory}</div>
            <div className="kn-sign-title">{profile.signatoryTitle}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
