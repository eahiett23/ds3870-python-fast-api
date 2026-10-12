'use strict';
// Production sessions remain in memory; refreshing the page requires sign-in.
objApp.token = null;
objApp.production = false;
function authHeaders() {
  return objApp.token ? {Authorization: `Bearer ${objApp.token}`} : {};
}
async function productionRequest(strPath, objOptions = {}) {
  const objResponse = await fetch(`/api${strPath}`, {...objOptions, headers: {'Content-Type':'application/json', ...authHeaders(), ...objOptions.headers}});
  const objData = await objResponse.json();
  if (!objResponse.ok) {
    if (objResponse.status === 401) {objApp.token = null; objApp.accountRole = null;}
    throw new Error(typeof objData.detail === 'string' ? objData.detail : 'Request failed. Check the supplied values.');
  }
  return objData;
}
function signInView() {
  elAppView.innerHTML = `<section class="section-pad"><div class="container" style="max-width:520px"><h1 class="h2">Sign in</h1><form id="login-form"><label class="form-label" for="login-email">Email</label><input id="login-email" name="email" type="email" class="form-control mb-3" autocomplete="username" required><label class="form-label" for="login-password">Password</label><input id="login-password" name="password" type="password" class="form-control mb-3" autocomplete="current-password" required><button class="btn btn-earth" type="submit">Sign in</button><p id="login-message" role="status" class="mt-3"></p></form></div></section>`;
}
async function initializeProduction() {
  elRoleToggle.disabled = true;
  try {
    const objConfig = await productionRequest('/config');
    if (objConfig.mode !== 'production') {elRoleToggle.disabled = false; return;}
    objApp.production = true;
    arrStages.splice(0, arrStages.length, ...objConfig.stages);
    elRoleToggle.parentElement.hidden = true;
    const elAccount = document.createElement('li');
    elAccount.className = 'nav-item';
    elAccount.innerHTML = '<button id="account-button" class="btn btn-outline-earth" type="button">Sign in</button><button id="workspace-button" class="btn btn-earth ms-2" type="button" hidden>My workspace</button>';
    elRoleToggle.parentElement.after(elAccount);
    document.getElementById('account-button').addEventListener('click', async () => {
      if (!objApp.token) {signInView(); return;}
      try {await productionRequest('/auth/logout', {method:'POST'});} catch (objError) {document.getElementById('notice-text').textContent = objError.message;}
      objApp.token = null; objApp.accountRole = null;
      document.getElementById('account-button').textContent = 'Sign in';
      document.getElementById('workspace-button').hidden = true;
      showView('landing');
    });
    document.getElementById('workspace-button').addEventListener('click', () => showView(objApp.accountRole));
    const fnLanding = landingView;
    landingView = () => fnLanding().replace('<option>Additive &amp; Subtractive Manufacturing</option>', '<option>3D Printing</option><option>CNC Machining</option>').replace('<option>Not sure yet</option>', '');
    fetchJobs = strRole => productionRequest(`/jobs?role=${encodeURIComponent(strRole)}`);
    const fnCustomerCard = customerJobCard;
    customerJobCard = objJob => fnCustomerCard(objJob).replace('</article>', `<div class="mt-3"><strong>${objJob.progress_percentage}% complete</strong><p class="mb-1">${escapeHtml(objJob.carrier_name || '')} ${escapeHtml(objJob.tracking_number || '')}</p>${objJob.tracking_url?.startsWith('https://') ? `<a href="${escapeHtml(objJob.tracking_url)}" target="_blank" rel="noopener noreferrer">Track shipment</a>` : ''}<button class="btn btn-outline-earth btn-sm ms-2 history-button" data-id="${escapeHtml(objJob.id)}" type="button">View timeline</button><div class="job-history mt-2" aria-live="polite"></div></div></article>`);
    const fnCustomerView = customerView;
    customerView = async () => {
      await fnCustomerView();
      const elNote = document.querySelector('#customer-jobs + p');
      if (elNote) elNote.textContent = 'Your active and archived projects. New inquiries appear after our team reviews and converts them.';
    };
    const fnAdminCard = adminJobCard;
    adminJobCard = objJob => fnAdminCard(objJob).replace('data-job-id=', `data-version="${objJob.version}" data-job-id=`).replace('</article>', `<div class="row g-3 mt-2">${[
      ['progress','Progress (%)','number',objJob.progress_percentage],
      ['actual-completion','Actual completion','date',objJob.actual_completion_date],
      ['actual-shipping','Actual shipping','date',objJob.actual_shipping_date],
      ['carrier','Carrier','text',objJob.carrier_name],
      ['tracking','Tracking number','text',objJob.tracking_number],
      ['tracking-url','Tracking URL','url',objJob.tracking_url]
    ].map(([strKey,strLabel,strType,objValue]) => `<div class="col-md-4"><label for="${strKey}-${objJob.id}" class="form-label">${strLabel}</label><input id="${strKey}-${objJob.id}" class="form-control job-${strKey}" type="${strType}" ${strKey === 'progress' ? 'min="0" max="100"' : ''} value="${escapeHtml(objValue ?? '')}"></div>`).join('')}</div></article>`);
    adminView = async () => {
      elAppView.innerHTML = '<section class="section-pad"><div class="container"><h1 class="h2">Inquiry &amp; job board</h1><div id="admin-jobs" aria-live="polite">Loading…</div></div></section>';
      try {
        const objData = await fetchJobs('admin');
        document.getElementById('admin-jobs').innerHTML = `<h2 class="h4 mt-4">Inquiries</h2>${objData.inquiries.map(objItem => `<article class="job-card p-3 mb-3"><h3 class="h5">${escapeHtml(objItem.service)} · ${escapeHtml(objItem.customer_name)}</h3><p>${escapeHtml(objItem.email)} · ${escapeHtml(objItem.status)}</p><p>${escapeHtml(objItem.project_details)}</p>${!['converted','rejected'].includes(objItem.status) ? `<form class="conversion-form" data-id="${objItem.id}"><label class="form-label" for="owner-${objItem.id}">Customer account ID</label><input id="owner-${objItem.id}" name="customer_id" class="form-control mb-2" type="number" min="1" value="${objItem.customer_id || ''}" required><label class="form-label" for="title-${objItem.id}">Job title</label><input id="title-${objItem.id}" name="title" class="form-control mb-2" minlength="2" maxlength="240" required><button class="btn btn-earth" type="submit">Create customer job</button><p class="conversion-message mt-2" role="status"></p></form>` : ''}</article>`).join('') || '<p>No inquiries.</p>'}<h2 class="h4 mt-4">Jobs</h2>${objData.jobs.map(adminJobCard).join('') || '<p>No jobs.</p>'}`;
      } catch (objError) {document.getElementById('admin-jobs').textContent = objError.message;}
    };
    showView('landing');
  } catch (objError) {elAppView.textContent = `Unable to load application configuration: ${objError.message}`;}
}
document.addEventListener('submit', async objEvent => {
  if (!objApp.production) return;
  const elForm = objEvent.target;
  if (elForm.id !== 'login-form' && !elForm.matches('.conversion-form')) return;
  objEvent.preventDefault();
  const objPayload = Object.fromEntries(new FormData(elForm).entries());
  const elMessage = elForm.querySelector('#login-message, .conversion-message');
  const elSubmit = elForm.querySelector('[type="submit"]');
  elSubmit.disabled = true;
  try {
    if (elForm.id === 'login-form') {
      const objData = await productionRequest('/auth/login', {method:'POST', body:JSON.stringify(objPayload)});
      objApp.token = objData.access_token; objApp.accountRole = objData.role;
      document.getElementById('account-button').textContent = 'Sign out';
      document.getElementById('workspace-button').hidden = false;
      showView(objData.role);
    } else {
      objPayload.customer_id = Number(objPayload.customer_id);
      await productionRequest(`/inquiries/${elForm.dataset.id}/convert`, {method:'POST', body:JSON.stringify(objPayload)});
      await adminView();
    }
  } catch (objError) {elMessage.textContent = objError.message;}
  finally {elSubmit.disabled = false;}
});
document.addEventListener('click', async objEvent => {
  if (!objApp.production) return;
  const elHistory = objEvent.target.closest('.history-button');
  const elSave = objEvent.target.closest('.save-job');
  if (!elSave && !elHistory) return;
  objEvent.stopImmediatePropagation();
  objEvent.preventDefault();
  if (elHistory) {
    const elTarget = elHistory.nextElementSibling;
    try {const objData = await productionRequest(`/jobs/${elHistory.dataset.id}/milestones`); elTarget.innerHTML = objData.milestones.map(objItem => `<p><strong>${escapeHtml(objItem.created_at)} · ${escapeHtml(objItem.stage)} (${objItem.progress_percentage}%)</strong><br>${escapeHtml(objItem.note)}</p>`).join('') || 'No updates yet.';}
    catch (objError) {elTarget.textContent = objError.message;}
    return;
  }
  const elCard = elSave.closest('[data-job-id]');
  const elResult = elCard.querySelector('.save-result');
  const fnValue = strClass => elCard.querySelector(`.job-${strClass}`).value || null;
  const objPayload = {status:fnValue('status'), version:Number(elCard.dataset.version),
    progress_percentage:Number(fnValue('progress')), estimated_completion_date:fnValue('completion'),
    estimated_shipping_date:fnValue('shipping'), actual_completion_date:fnValue('actual-completion'),
    actual_shipping_date:fnValue('actual-shipping'), carrier_name:fnValue('carrier'),
    tracking_number:fnValue('tracking'), tracking_url:fnValue('tracking-url')};
  elSave.disabled = true;
  try {
    const objData = await productionRequest(`/jobs/${elCard.dataset.jobId}`, {method:'PUT', body:JSON.stringify(objPayload)});
    elCard.dataset.version = objData.job.version;
    elResult.textContent = 'Saved';
  } catch (objError) {elResult.textContent = objError.message;}
  finally {elSave.disabled = false;}
}, true);
initializeProduction();
