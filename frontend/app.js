const message = document.querySelector('#message');
const instructions = document.querySelector('#instructions');
const screenshot = document.querySelector('#screenshot');
const resumeFile = document.querySelector('#resume-file');
const dropzone = document.querySelector('#dropzone');
const chooseFile = document.querySelector('#choose-file');
const changeResume = document.querySelector('#change-resume');
const analyzeButton = document.querySelector('#analyze-button');
const regenerateButton = document.querySelector('#regenerate-button');
const editButton = document.querySelector('#edit-button');
const clearButton = document.querySelector('#clear-button');
const approveButton = document.querySelector('#approve-button');
const gmailConnect = document.querySelector('#gmail-connect');
const gmailLabel = document.querySelector('#gmail-label');
const gmailAccount = document.querySelector('#gmail-account');
const gmailLogout = document.querySelector('#gmail-logout');
const refineInstruction = document.querySelector('#refine-instruction');
const refineButton = document.querySelector('#refine-button');
const fileName = document.querySelector('#file-name');
const progress = document.querySelector('#progress');
const draft = document.querySelector('#draft');
const draftEmpty = document.querySelector('.draft-empty');
const detailsEmpty = document.querySelector('#details-empty');
const detailsContent = document.querySelector('#details-content');
const detailsState = document.querySelector('#details-state');
const draftState = document.querySelector('#draft-state');
let selectedFile = null;
let extractedText = '';
let candidateEmails = [];
let draftIsEditing = false;
let gmailConnected = false;

function count(input, output, max) { output.textContent = `${input.value.length} / ${max}`; }
message.addEventListener('input', () => count(message, document.querySelector('#message-count'), 8000));
instructions.addEventListener('input', () => count(instructions, document.querySelector('#instructions-count'), 1000));
chooseFile.addEventListener('click', () => screenshot.click());
screenshot.addEventListener('change', () => setScreenshot(screenshot.files[0]));
dropzone.addEventListener('click', event => { if (event.target !== chooseFile) screenshot.click(); });
['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove('dragging'); }));
dropzone.addEventListener('drop', event => setScreenshot(event.dataTransfer.files[0]));
changeResume.addEventListener('click', () => resumeFile.click());
resumeFile.addEventListener('change', async () => {
  const file = resumeFile.files[0];
  if (!file) return;
  const form = new FormData(); form.append('file', file); changeResume.disabled = true;
  try { const response = await fetch('/resume', { method:'POST', body:form }); if (!response.ok) throw new Error((await response.json()).detail); await loadResume(); }
  catch (error) { progress.textContent = error.message; } finally { changeResume.disabled = false; }
});
function setScreenshot(file) { if (!file) return; selectedFile = file; fileName.textContent = `Selected: ${file.name}`; }
function parseSse(block) { const type = block.split('\n')[0]?.replace('event: ', ''); const line = block.split('\n').find(item => item.startsWith('data: ')); return line ? { type, data: JSON.parse(line.slice(6)) } : null; }
async function readStream(response, onEvent) {
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream:true }); const blocks = buffer.split('\n\n'); buffer = blocks.pop(); blocks.filter(Boolean).forEach(block => { const event = parseSse(block); if (event) onEvent(event); }); }
  if (buffer.trim()) { const event = parseSse(buffer); if (event) onEvent(event); }
}
async function loadResume() {
  const data = await fetch('/resume').then(response => response.json());
  document.querySelector('#resume-name').textContent = data.name || 'No resume configured';
  document.querySelector('#resume-size').textContent = data.size_bytes ? `${Math.ceil(data.size_bytes / 1024)} KB` : 'Add a PDF, TXT, MD, or JSON file';
}
async function analyze() {
  if (!message.value.trim() && !selectedFile) { progress.textContent = 'Paste a job post or choose a screenshot first.'; return; }
  analyzeButton.disabled = true; analyzeButton.textContent = 'Reading source...'; detailsState.textContent = 'Analyzing';
  try {
    let text = message.value.trim();
    if (selectedFile) { const form = new FormData(); form.append('file', selectedFile); const response = await fetch('/analyze', { method:'POST', body:form }); const data = await response.json(); if (!data.success) throw new Error(data.error || 'OCR failed'); text = data.text; candidateEmails = data.candidate_emails || []; }
    extractedText = text;
    const response = await fetch('/extract-job', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ text, candidate_emails:candidateEmails }) });
    const data = await response.json(); if (!data.success) throw new Error(data.error || 'Job extraction failed');
    const job = data.job || {};
    if (!candidateEmails.length && job.recipient_email) candidateEmails = [job.recipient_email];
    document.querySelector('#detail-company').textContent = job.company || '-'; document.querySelector('#detail-role').textContent = job.role || '-'; document.querySelector('#detail-location').textContent = job.location || '-'; document.querySelector('#detail-email').textContent = job.recipient_email || '-'; document.querySelector('#detail-requirements').textContent = (job.requirements || []).join(', ') || '-';
    detailsEmpty.classList.add('hidden'); detailsContent.classList.remove('hidden'); detailsState.textContent = 'Analyzed'; detailsState.classList.add('ready'); progress.textContent = 'Job details extracted. Generate the email draft when ready.';
    await generateDraft();
  } catch (error) { progress.textContent = error.message; detailsState.textContent = 'Needs attention'; } finally { analyzeButton.disabled = false; analyzeButton.textContent = '✣  Analyze & Extract Details'; }
}
async function generateDraft() {
  if (!extractedText) return;
  regenerateButton.disabled = true; refineButton.disabled = true; setDraftEditing(false); draftState.textContent = 'Writing...'; draftEmpty.classList.add('hidden'); draft.classList.remove('hidden'); draft.value = ''; approveButton.disabled = true;
  const form = new FormData(); form.append('message', extractedText); form.append('instructions', instructions.value);
  try { const response = await fetch('/draft', { method:'POST', body:form }); if (!response.ok) throw new Error((await response.json()).detail); await readStream(response, event => { if (event.type === 'status') progress.textContent = event.data.message; if (event.type === 'draft_token') draft.value += event.data.text; if (event.type === 'complete') { draftState.textContent = 'Draft ready'; approveButton.disabled = false; splitDraft(); } if (event.type === 'error') throw new Error(event.data.message); }); }
  catch (error) { progress.textContent = error.message; draftState.textContent = 'Needs attention'; } finally { regenerateButton.disabled = false; refineButton.disabled = !draft.value.trim(); }
}
async function refineDraft() {
  const instruction = refineInstruction.value.trim();
  if (!draft.value.trim()) { progress.textContent = 'Generate a draft before asking for an edit.'; return; }
  if (!instruction) { progress.textContent = 'Describe the edit you want to make.'; refineInstruction.focus(); return; }
  refineButton.disabled = true; regenerateButton.disabled = true; editButton.disabled = true; approveButton.disabled = true; setDraftEditing(false); draftState.textContent = 'Updating...'; progress.textContent = 'Applying your edit...';
  const form = new FormData(); form.append('instruction', instruction); form.append('current_draft', draft.value); form.append('posting', extractedText);
  try { const response = await fetch('/refine', { method:'POST', body:form }); if (!response.ok) throw new Error((await response.json()).detail); draft.value = ''; await readStream(response, event => { if (event.type === 'status') progress.textContent = event.data.message; if (event.type === 'draft_token') draft.value += event.data.text; if (event.type === 'complete') { draftState.textContent = 'Draft ready'; approveButton.disabled = false; splitDraft(); } if (event.type === 'error') throw new Error(event.data.message); }); refineInstruction.value = ''; }
  catch (error) { progress.textContent = error.message; draftState.textContent = 'Needs attention'; }
  finally { refineButton.disabled = !draft.value.trim(); regenerateButton.disabled = false; editButton.disabled = false; }
}
function splitDraft() { const lines = draft.value.split('\n'); const subjectIndex = lines.findIndex(line => /^\*{0,2}subject\*{0,2}\s*:/i.test(line)); if (subjectIndex >= 0) document.querySelector('#draft-subject').textContent = lines[subjectIndex].replace(/^\*{0,2}subject\*{0,2}\s*:\s*/i, '').replace(/\*{2}$/,'').trim(); const to = candidateEmails[0] || '—'; document.querySelector('#draft-to').textContent = to; }
function updateGmailStatus(data) { gmailConnected = Boolean(data.connected); gmailLabel.textContent = gmailConnected ? 'Logged in' : 'Connect Gmail'; gmailAccount.textContent = data.account || (gmailConnected ? 'Gmail account ready' : 'Authorize before sending'); gmailConnect.disabled = gmailConnected; gmailLogout.classList.toggle('hidden', !gmailConnected); }
async function loadGmailStatus() { try { updateGmailStatus(await fetch('/gmail/status').then(response => response.json())); } catch (error) { gmailAccount.textContent = 'Gmail status unavailable'; } }
async function logoutGmail() { gmailLogout.disabled = true; try { const response = await fetch('/auth/gmail/logout', { method:'POST' }); updateGmailStatus(await response.json()); progress.textContent = 'Gmail disconnected.'; } catch (error) { progress.textContent = 'Could not disconnect Gmail.'; } finally { gmailLogout.disabled = false; } }
async function sendDraft() {
  if (!draft.value.trim()) { progress.textContent = 'Generate a draft before sending it.'; return; }
  if (!candidateEmails[0]) { progress.textContent = 'No trusted recipient email was found.'; return; }
  const lines = draft.value.split('\n'); const subjectIndex = lines.findIndex(line => /^\*{0,2}subject\*{0,2}\s*:/i.test(line));
  const subject = subjectIndex >= 0 ? lines[subjectIndex].replace(/^\*{0,2}subject\*{0,2}\s*:\s*/i, '').replace(/\*{2}$/,'').trim() : '';
  const body = subjectIndex >= 0 ? lines.slice(subjectIndex + 1).join('\n').trim() : draft.value.trim();
  if (!subject || !body) { progress.textContent = 'The draft needs a subject and body before sending.'; return; }
  approveButton.disabled = true; gmailConnect.disabled = true; progress.textContent = 'Sending through Gmail...';
  const form = new FormData(); form.append('recipient', candidateEmails[0]); form.append('subject', subject); form.append('body', body);
  try { const response = await fetch('/gmail/send', { method:'POST', body:form }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Gmail send failed'); draftState.textContent = 'Sent'; progress.textContent = `Email sent to ${candidateEmails[0]} with the candidate resume attached.`; approveButton.textContent = '✓ Sent via Gmail'; }
  catch (error) { progress.textContent = error.message; approveButton.disabled = false; }
  finally { gmailConnect.disabled = false; }
}
function setDraftEditing(editing) { draftIsEditing = editing; draft.readOnly = !editing; editButton.textContent = editing ? '✓  Save Draft' : '✎  Edit Draft'; draftState.textContent = editing ? 'Editing' : 'Draft ready'; if (editing) draft.focus(); else splitDraft(); }
analyzeButton.addEventListener('click', analyze); regenerateButton.addEventListener('click', generateDraft); editButton.addEventListener('click', () => { if (!draft.value.trim()) { progress.textContent = 'Generate a draft before editing it.'; return; } setDraftEditing(!draftIsEditing); });
refineButton.addEventListener('click', refineDraft); refineInstruction.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); refineDraft(); } });
clearButton.addEventListener('click', () => { message.value=''; instructions.value=''; refineInstruction.value=''; refineButton.disabled=true; selectedFile=null; extractedText=''; draft.value=''; draft.classList.add('hidden'); draftEmpty.classList.remove('hidden'); detailsContent.classList.add('hidden'); detailsEmpty.classList.remove('hidden'); detailsState.textContent='Not analyzed'; draftState.textContent='No draft yet'; approveButton.disabled=true; setDraftEditing(false); count(message, document.querySelector('#message-count'), 8000); count(instructions, document.querySelector('#instructions-count'), 1000); });
gmailConnect.addEventListener('click', () => { if (!gmailConnected) window.location.href = '/auth/gmail/start'; });
gmailLogout.addEventListener('click', logoutGmail);
approveButton.addEventListener('click', sendDraft);
loadResume().catch(() => { document.querySelector('#resume-name').textContent = 'Resume unavailable'; });
loadGmailStatus();
