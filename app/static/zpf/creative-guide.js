/* The guide develops a brief; only the existing Create button writes scenes. */
import { api, esc } from './shared.js';
import { initModelConnections } from './model-connections.js';

export function initCreativeGuide(collectReferences, references) {
  const $ = id => document.getElementById(id);
  const panel = $('cbox');
  const input = $('prompt');
  const modelConnections = initModelConnections();
  let messages = [];
  let busy = false;
  let pending = null;
  let pendingMessages = null;
  let projectId = null;
  let revision = 0;
  let saving = false;
  let dirty = false;
  let restoring = false;
  const projectSelect = $('guideproject');
  const saveStatus = $('guidesavestatus');
  const headers = { 'X-ZPF-Model-Connection': '1' };

  function markDirty() {
    if (restoring) return;
    dirty = true;
    saveStatus.textContent = 'Unsaved changes';
  }
  async function refreshProjects() {
    const data = await api('/api/creative-projects');
    projectSelect.innerHTML = '<option value="">New project</option>' + data.projects.map(p =>
      `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
    projectSelect.value = projectId || '';
  }
  async function saveProject() {
    if (saving) throw new Error('Wait for the project to finish saving.');
    if (references.hasUploads()) throw new Error('Send your direction first to save the attached uploads with this project.');
    saving = true;
    projectSelect.disabled = true;
    $('guidesave').disabled = true;
    $('guidesend').disabled = true;
    $('guidereset').disabled = true;
    saveStatus.textContent = 'Saving…';
    const payload = { messages, brief: $('guidebrief').value, input: input.value, refs: references.getRefs() };
    const title = (messages[0]?.content || input.value || payload.brief || 'Untitled project').slice(0, 120);
    dirty = false;
    try {
      const saved = await api('/api/creative-projects', {method:'POST', headers,
        body: {id: projectId, revision, title, payload}});
      projectId = saved.id;
      revision = saved.revision;
      await refreshProjects();
      saveStatus.textContent = dirty ? 'Unsaved changes' : 'Saved';
    } catch (e) {
      dirty = true;
      saveStatus.textContent = `Not saved: ${e.message}`;
      throw e;
    } finally {
      saving = false;
      projectSelect.disabled = busy;
      $('guidesave').disabled = busy;
      $('guidesend').disabled = busy;
      $('guidereset').disabled = busy;
    }
  }
  $('guidesave').onclick = () => saveProject().catch(e => { saveStatus.textContent = e.message; });
  panel.addEventListener('referenceschange', markDirty);
  input.addEventListener('input', markDirty);
  $('guidebrief').addEventListener('input', markDirty);
  window.addEventListener('beforeunload', e => {
    if (dirty || busy || saving) { e.preventDefault(); e.returnValue = ''; }
  });
  projectSelect.onchange = async () => {
    const target = projectSelect.value;
    projectSelect.value = projectId || '';
    if (busy || saving) return;
    try {
      if (dirty) await saveProject();
      if (!target) { await reset(); return; }
      setBusy(true);
      const saved = await api(`/api/creative-projects/${encodeURIComponent(target)}`);
      restoring = true;
      projectId = saved.id; revision = saved.revision;
      messages = saved.payload.messages || [];
      input.value = saved.payload.input || '';
      $('guidebrief').value = saved.payload.brief || '';
      $('guidebriefwrap').hidden = !$('guidebrief').value;
      $('guidechoices').innerHTML = '';
      references.restoreRefs(saved.payload.refs || []);
      render();
      input.dispatchEvent(new Event('input'));
      dirty = false;
      projectSelect.value = projectId;
      saveStatus.textContent = 'Saved project restored';
      $('guidestatus').textContent = 'Continue the conversation, or review the saved brief.';
    } catch (e) { saveStatus.textContent = e.message; }
    finally { restoring = false; setBusy(false); }
  };

  function render() {
    $('guidemessages').innerHTML = messages.map(m =>
      `<div class="guide-message ${m.role}"><b>${m.role === 'user' ? 'You' : 'Creative guide'}</b><p>${esc(m.content)}</p></div>`).join('');
    $('guidemessages').scrollTop = $('guidemessages').scrollHeight;
  }
  function setBusy(value) {
    busy = value;
    modelConnections.setLocked(value || !!pending);
    $('guidesend').disabled = value;
    $('guidereset').disabled = value || saving;
    $('guidesave').disabled = value || saving;
    projectSelect.disabled = value || saving || !!pending;
    input.disabled = value;
    $('go').disabled = value || !!pending || !!input.value.trim() || !$('guidebrief').value.trim();
    $('guidebrief').disabled = value;
    panel.querySelectorAll('[data-choice]').forEach(b => b.disabled = value);
    panel.setAttribute('aria-busy', String(value));
  }
  async function send(text) {
    if (busy || saving || (!text.trim() && !pending)) return;
    if (!pending && messages.length >= 40) {
      $('guidestatus').textContent = 'Create scenes from your latest brief, or start a new conversation to continue.';
      return;
    }
    setBusy(true);
    $('guidestudio').hidden = true;
    $('guidestatus').textContent = 'Considering your direction…';
    try {
      if (!pending) {
        // Include the idea once; subsequent turns carry the actual conversation.
        const draft = $('guidebrief').value.trim();
        const content = messages.length && draft ? `${text.trim()}\n\nCurrent editable brief:\n${draft}` : text.trim();
        pendingMessages = [...messages, { role: 'user', content }];
        const form = collectReferences($('prompt').value.trim());
        modelConnections.appendTo(form);
        form.append('conversation', JSON.stringify({ messages: pendingMessages }));
        const started = await api('/api/creative-guide', { method: 'POST', headers: { 'X-ZPF-Model-Connection': '1' }, body: form });
        pending = started.job_id;
      }
      // Keep the job id after a network failure: Retry resumes this job,
      // rather than paying for another identical reasoning call.
      let job;
      while (true) {
        job = await api(`/api/jobs/${pending}`);
        if (['done', 'failed', 'cancelled'].includes(job.status)) break;
        $('guidestatus').textContent = job.detail || 'Considering your direction…';
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
      pending = null;
      if (job.status !== 'done') throw new Error(job.error || 'The guide stopped. Your reply is still here to retry.');
      const reply = job.reply;
      messages = [...pendingMessages, { role: 'assistant', content: reply.message +
        (reply.brief ? `\n\nDraft brief:\n${reply.brief}` : '') }];
      input.value = '';
      input.dispatchEvent(new Event('input'));
      render();
      $('guidechoices').innerHTML = (reply.choices || []).map((c, i) =>
        `<button type="button" class="chip" data-choice="${i}">${esc(c)}</button>`).join('');
      panel.querySelectorAll('[data-choice]').forEach(b => b.onclick = () => {
        input.value = reply.choices[Number(b.dataset.choice)];
        send(input.value);
      });
      $('guidebriefwrap').hidden = !reply.brief;
      $('guidebrief').value = reply.brief || '';
      $('guidestatus').textContent = reply.brief ? 'Refine the direction above, or review the brief and create scenes.' : 'Choose a direction or reply in your own words.';
      $('guidesend').textContent = 'Send';
      references.restoreRefs(job.reference_urls || references.getRefs());
      dirty = true;
      try { await saveProject(); } catch (e) { saveStatus.textContent = `Reply ready, but not saved: ${e.message}`; }
    } catch (e) {
      if (e.status === 404) pending = null; // server restarted / job was cleared
      $('guidestatus').textContent = e.message;
      $('guidestudio').hidden = !(e.status === 409 && !pending && $('guideprovider').value !== 'gemini');
      $('guidesend').textContent = pending ? 'Retry response' : 'Retry';
    } finally {
      setBusy(false);
      input.focus();
    }
  }
  $('guidestudio').onclick = () => {
    if (busy || saving || pending) return;
    modelConnections.useStudio();
    $('guidestudio').hidden = true;
    send(input.value);
  };
  $('guidesend').onclick = () => send(input.value);
  function syncCreate() {
    $('go').disabled = busy || !!pending || !!input.value.trim() || !$('guidebrief').value.trim();
  }
  input.addEventListener('input', syncCreate);
  $('guidebrief').addEventListener('input', syncCreate);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && $('promptmentions').hidden) {
      e.preventDefault(); send(input.value);
    }
  });
  async function reset() {
    if (busy || saving) return;
    if (dirty) {
      try { await saveProject(); } catch (e) { saveStatus.textContent = e.message; return; }
    }
    restoring = true;
    projectId = null; revision = 0;
    projectSelect.value = '';
    saveStatus.textContent = '';
    references.restoreRefs([]);
    messages = [];
    pending = null;
    pendingMessages = null;
    render();
    $('guidechoices').innerHTML = '';
    $('guidebriefwrap').hidden = true;
    $('guidebrief').value = '';
    input.value = '';
    $('guidestatus').textContent = 'Tell me what you have in mind, or ask me to suggest a direction.';
    $('guidesend').textContent = 'Send';
    setBusy(false);
    input.dispatchEvent(new Event('input'));
    dirty = false; restoring = false;
  }
  $('guidereset').onclick = reset;
  // Initial setup must not clear references that other composer tools may attach.
  refreshProjects().catch(e => { saveStatus.textContent = `Saved projects unavailable: ${e.message}`; });
  $('guidestatus').textContent = 'Describe your idea to start a project, or open a saved one.';
  return { reset, setBusy };
}
