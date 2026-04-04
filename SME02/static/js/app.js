/**
 * SME02 — Frontend Application
 * ==============================
 * Handles SSE streaming, agent feed rendering, review/approval flow,
 * PDF download, New RFP reset, and job history.
 */

// ---- State ----
const state = {
    jobId: null,
    status: 'idle',
    changes: [],
    jobData: null, // stores requirements, pricing, proposal
    uploadFile: null, // stores explicitly dropped/selected file
    inputMode: 'upload', // 'upload' or 'paste'
    history: [], // local history of processed jobs
};

// ---- DOM Elements ----
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    globalStatus: $('#globalStatus'),
    rfpInput: $('#rfpInput'),
    charCount: $('#charCount'),
    processBtn: $('#processBtn'),
    loadExampleBtn: $('#loadExampleBtn'),
    heroSection: $('#heroSection'),
    inputSection: $('#inputSection'),
    agentSection: $('#agentSection'),
    reviewSection: $('#reviewSection'),
    downloadSection: $('#downloadSection'),
    feedContainer: $('#feedContainer'),
    chipAnalyst: $('#chipAnalyst'),
    chipStrategist: $('#chipStrategist'),
    chipCopywriter: $('#chipCopywriter'),
    reviewTabs: $('#reviewTabs'),
    reviewContent: $('#reviewContent'),
    changesList: $('#changesList'),
    changeAgent: $('#changeAgent'),
    changeInstruction: $('#changeInstruction'),
    addChangeBtn: $('#addChangeBtn'),
    approveBtn: $('#approveBtn'),
    submitChangesBtn: $('#submitChangesBtn'),
    downloadPdfBtn: $('#downloadPdfBtn'),
    downloadMeta: $('#downloadMeta'),
    companyName: $('#companyName'),
    contactName: $('#contactName'),
    contactEmail: $('#contactEmail'),
    
    // File upload elements
    dropZone: $('#dropZone'),
    browseFileBtn: $('#browseFileBtn'),
    fileInput: $('#fileInput'),
    selectedFile: $('#selectedFile'),
    fileName: $('#fileName'),
    fileSize: $('#fileSize'),
    removeFileBtn: $('#removeFileBtn'),

    // New RFP & History
    newRfpBtn: $('#newRfpBtn'),
    newRfpHeaderBtn: $('#newRfpHeaderBtn'),
    historyBtn: $('#historyBtn'),
    historyModal: $('#historyModal'),
    closeHistoryBtn: $('#closeHistoryBtn'),
    historyList: $('#historyList'),
};

// ---- Example RFP ----
const EXAMPLE_RFP = `## Request for Proposal (RFP) - IT Infrastructure Upgrade
**Issued By:** Tech Solutions Inc.
**Date Issued:** April 2, 2026
**Response Deadline:** April 16, 2026

### 1. Introduction
Tech Solutions Inc. is seeking proposals from qualified vendors for a comprehensive IT infrastructure upgrade for our main office in Bangalore, India. This project aims to modernize our server room, upgrade network equipment, and implement robust virtualization across our operations.

### 2. Scope of Work
We require the following services and hardware:
*   **Server Hardware:** Supply and install 5 new rack-mounted servers (Dell PowerEdge R760 or equivalent) with minimum specs: 2x Intel Xeon Gold 6448Y, 512GB DDR5 RAM, 4x 1.92TB NVMe SSD.
*   **Network Equipment:** Supply and install 2 core switches (Cisco Catalyst 9300 or equivalent) and 10 access switches (Cisco Catalyst 9200 or equivalent).
*   **Virtualization Software:** License and configure VMware vSphere Enterprise Plus for all 5 hosts.
*   **Data Migration:** Migrate existing data (~10TB) from old servers to new infrastructure with zero data loss.
*   **Installation & Configuration:** Full installation and configuration of all hardware and software.
*   **Training:** Provide 2 days of on-site training for our IT staff.
*   **Support:** 1-year premium support package for all hardware and software.

### 3. Project Timeline
*   **Phase 1 (Hardware Procurement):** 4 weeks from contract signing.
*   **Phase 2 (Installation & Configuration):** 3 weeks after hardware delivery.
*   **Phase 3 (Data Migration & Training):** 2 weeks after installation.
*   **Project Completion:** Within 9 weeks of contract signing.

### 4. Budget
Our indicative budget for this project is **₹50,00,000** (Fifty Lakh Indian Rupees), exclusive of applicable taxes.

### 5. Evaluation Criteria
Proposals will be evaluated based on:
*   Technical Solution (40%)
*   Pricing (30%)
*   Vendor Experience (20%)
*   Support & Maintenance (10%)

### 6. Submission Requirements
Proposals must include:
*   Executive Summary
*   Detailed Technical Proposal
*   Project Plan & Timeline
*   Detailed Cost Breakdown
*   Company Profile & References
*   Proposed Support & Maintenance Plan

**Contact:** procurement@techsolutions.com`;

// ---- Initialization ----
document.addEventListener('DOMContentLoaded', () => {
    // Load history from localStorage
    loadHistory();

    // Character counter
    els.rfpInput.addEventListener('input', () => {
        els.charCount.textContent = `${els.rfpInput.value.length} characters`;
    });

    // Load example
    els.loadExampleBtn.addEventListener('click', () => {
        els.rfpInput.value = EXAMPLE_RFP;
        els.charCount.textContent = `${EXAMPLE_RFP.length} characters`;
        els.rfpInput.style.height = 'auto';
        els.rfpInput.style.height = els.rfpInput.scrollHeight + 'px';
    });

    // Process RFP
    els.processBtn.addEventListener('click', startProcessing);

    // Review tabs
    $$('.review-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Add change
    els.addChangeBtn.addEventListener('click', addChange);
    els.changeInstruction.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addChange();
    });

    // Approve
    els.approveBtn.addEventListener('click', approveProposal);

    // Submit changes
    els.submitChangesBtn.addEventListener('click', submitChanges);

    // Input mode tabs
    $$('.input-tab').forEach(tab => {
        tab.addEventListener('click', () => setInputMode(tab.dataset.mode));
    });

    // File Drag & Drop
    els.dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        els.dropZone.classList.add('dragover');
    });
    els.dropZone.addEventListener('dragleave', () => {
        els.dropZone.classList.remove('dragover');
    });
    els.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        els.dropZone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    // File Click — entire drop zone is clickable
    els.dropZone.addEventListener('click', () => els.fileInput.click());
    els.browseFileBtn.addEventListener('click', (e) => {
        e.stopPropagation(); // prevent double-trigger from zone click
        els.fileInput.click();
    });
    els.fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    // Remove File
    els.removeFileBtn.addEventListener('click', () => {
        state.uploadFile = null;
        els.fileInput.value = '';
        els.selectedFile.classList.add('hidden');
        els.dropZone.style.display = 'block';
    });

    // ---- New RFP Buttons ----
    els.newRfpBtn.addEventListener('click', startNewRfp);
    els.newRfpHeaderBtn.addEventListener('click', startNewRfp);

    // ---- History ----
    els.historyBtn.addEventListener('click', openHistory);
    els.closeHistoryBtn.addEventListener('click', closeHistory);
    els.historyModal.addEventListener('click', (e) => {
        // Close when clicking the overlay backdrop
        if (e.target === els.historyModal) closeHistory();
    });
});

// ---- Input Modes & File ----
function setInputMode(mode) {
    state.inputMode = mode;
    $$('.input-tab').forEach(t => t.classList.remove('active'));
    $$('.input-mode-content').forEach(c => c.classList.remove('active'));
    
    $(`.input-tab[data-mode="${mode}"]`).classList.add('active');
    $(`#mode-${mode}`).classList.add('active');
}

function handleFileSelect(file) {
    const validTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain'];
    const validExts = ['.pdf', '.docx', '.txt'];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!validTypes.includes(file.type) && !validExts.includes(ext)) {
        alert("Invalid file type. Please upload a PDF, DOCX, or TXT file.");
        return;
    }
    
    state.uploadFile = file;
    
    // Convert size to human readable
    let sizeStr = '';
    if (file.size < 1024 * 1024) {
        sizeStr = (file.size / 1024).toFixed(1) + ' KB';
    } else {
        sizeStr = (file.size / (1024 * 1024)).toFixed(1) + ' MB';
    }

    els.fileName.textContent = file.name;
    els.fileSize.textContent = sizeStr;
    
    els.dropZone.style.display = 'none';
    els.selectedFile.classList.remove('hidden');
}

// ---- Processing Flow ----
async function startProcessing() {
    // Validate input based on mode
    if (state.inputMode === 'upload' && !state.uploadFile) {
        alert('Please drop or select an RFP file first.');
        return;
    }
    
    const rfpText = els.rfpInput.value.trim();
    if (state.inputMode === 'paste' && !rfpText) {
        alert('Please paste an RFP document first.');
        return;
    }

    // Disable button
    els.processBtn.disabled = true;
    els.processBtn.innerHTML = '<span class="spinner"></span> Processing...';
    setGlobalStatus('processing', 'Processing RFP...');

    // Show agent section
    showSection('agentSection');
    clearFeed();
    resetAgentChips();

    try {
        let res;
        
        if (state.inputMode === 'upload') {
            // Upload via FormData
            const formData = new FormData();
            formData.append('file', state.uploadFile);
            formData.append('company_name', els.companyName.value || 'Ering Solutions');
            formData.append('contact_name', els.contactName.value || 'Sales Team');
            formData.append('contact_email', els.contactEmail.value || 'sales@eringsolutions.com');
            
            res = await fetch('/api/upload-rfp', {
                method: 'POST',
                body: formData,
            });
        } else {
            // Paste via JSON
            res = await fetch('/api/process-rfp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rfp_text: rfpText,
                    company_name: els.companyName.value || 'Ering Solutions',
                    contact_name: els.contactName.value || 'Sales Team',
                    contact_email: els.contactEmail.value || 'sales@eringsolutions.com',
                }),
            });
        }
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to process RFP');
        
        state.jobId = data.job_id;

        // Add to history immediately as "processing"
        addToHistory({
            job_id: state.jobId,
            status: 'processing',
            company_name: els.companyName.value || 'Ering Solutions',
            created_at: new Date().toISOString(),
            project_name: '',
            pdf_ready: false,
        });

        // Start SSE streaming
        streamAgentFeed(`/api/stream/${state.jobId}`);

    } catch (err) {
        console.error('Error:', err);
        setGlobalStatus('error', 'Connection Error');
        els.processBtn.disabled = false;
        els.processBtn.innerHTML = '⚡ Process RFP with AI Agents';
    }
}

function streamAgentFeed(url) {
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);

            if (msg.type === 'job_state') {
                // Final state message
                state.jobData = {
                    extracted_requirements: msg.extracted_requirements,
                    pricing_strategy: msg.pricing_strategy,
                    proposal_draft: msg.proposal_draft,
                };

                if (msg.job_status === 'awaiting_approval') {
                    eventSource.close();
                    onProcessingComplete();
                } else if (msg.job_status === 'completed') {
                    eventSource.close();
                    onPdfReady();
                } else if (msg.job_status === 'error') {
                    eventSource.close();
                    setGlobalStatus('error', 'Error');
                    updateHistoryStatus(state.jobId, 'error');
                }
                return;
            }

            // Regular agent message
            addFeedMessage(msg);
            updateAgentChips(msg);

        } catch (e) {
            console.warn('Parse error:', e);
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
    };
}

function onProcessingComplete() {
    setGlobalStatus('processing', 'Awaiting Approval');
    els.processBtn.disabled = false;
    els.processBtn.innerHTML = '⚡ Process RFP with AI Agents';

    // Update history with project name if available
    if (state.jobData && state.jobData.extracted_requirements) {
        const projectName = state.jobData.extracted_requirements.project_name || '';
        updateHistoryMeta(state.jobId, {
            status: 'awaiting_approval',
            project_name: projectName,
        });
    }

    // Show review section
    showSection('reviewSection');
    populateReview();
}

async function onPdfReady() {
    setGlobalStatus('success', 'PDF Ready');

    // --- FIX: Reset the approve button spinner ---
    els.approveBtn.disabled = false;
    els.approveBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12"/>
        </svg>
        Approve &amp; Generate PDF
    `;

    // Show download section
    showSection('downloadSection');
    
    const downloadUrl = `/api/download-pdf/${state.jobId}`;
    const filename = `SME02_Quotation_${state.jobId}.pdf`;

    // Update history
    updateHistoryMeta(state.jobId, {
        status: 'completed',
        pdf_ready: true,
    });

    // Modern Blob approach to force filename extension across all browsers
    try {
        els.downloadPdfBtn.innerHTML = '<span class="status-dot"></span> Preparing Download...';
        const response = await fetch(downloadUrl);
        if (!response.ok) {
            throw new Error(`Download endpoint returned ${response.status}`);
        }

        const contentType = (response.headers.get('content-type') || '').toLowerCase();
        if (!contentType.includes('application/pdf')) {
            throw new Error(`Unexpected response content type: ${contentType || 'unknown'}`);
        }

        const blob = await response.blob();
        const blobUrl = window.URL.createObjectURL(blob);
        
        els.downloadPdfBtn.href = blobUrl;
        els.downloadPdfBtn.setAttribute('download', filename);
        
        // Clean up the URL object after clicking
        els.downloadPdfBtn.onclick = () => {
            setTimeout(() => window.URL.revokeObjectURL(blobUrl), 100);
        };
        
        els.downloadPdfBtn.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download PDF Quotation
        `;
    } catch (e) {
        console.error('Blob preparation failed, falling back to direct link', e);
        els.downloadPdfBtn.href = downloadUrl;
        els.downloadPdfBtn.setAttribute('download', filename);
    }
    
    els.downloadMeta.textContent = `Proposal ${state.jobId.toUpperCase()} — Generated ${new Date().toLocaleString()}`;
}

// ---- Agent Feed ----
function clearFeed() {
    els.feedContainer.innerHTML = '';
}

function addFeedMessage(msg) {
    // Remove empty state
    const empty = els.feedContainer.querySelector('.feed-empty');
    if (empty) empty.remove();

    const agentEmoji = getAgentEmoji(msg.agent);
    const time = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '';

    const div = document.createElement('div');
    div.className = `feed-message type-${msg.type}`;
    div.innerHTML = `
        <div class="feed-avatar">${agentEmoji}</div>
        <div class="feed-body">
            <div class="feed-header">
                <span class="feed-agent-name">${msg.agent}</span>
                <span class="feed-type-badge">${msg.type}</span>
                <span class="feed-time">${time}</span>
            </div>
            <div class="feed-content">${escapeHtml(msg.content)}</div>
        </div>
    `;

    els.feedContainer.appendChild(div);
    els.feedContainer.scrollTop = els.feedContainer.scrollHeight;
}

function getAgentEmoji(agent) {
    const map = {
        'Junior Analyst': '🔍',
        'Pricing Strategist': '📊',
        'Senior Copywriter': '✍️',
        'Orchestrator': '🤖',
        'PDF Generator': '📄',
    };
    return map[agent] || '⚙️';
}

function updateAgentChips(msg) {
    const agentChipMap = {
        'Junior Analyst': els.chipAnalyst,
        'Pricing Strategist': els.chipStrategist,
        'Senior Copywriter': els.chipCopywriter,
    };

    const chip = agentChipMap[msg.agent];
    if (!chip) return;

    if (msg.type === 'complete') {
        chip.dataset.status = 'complete';
        chip.querySelector('.agent-chip-status').textContent = 'Complete ✓';
    } else if (msg.type === 'error') {
        chip.dataset.status = 'error';
        chip.querySelector('.agent-chip-status').textContent = 'Error';
    } else {
        chip.dataset.status = 'active';
        chip.querySelector('.agent-chip-status').textContent = 'Working...';
    }
}

function resetAgentChips() {
    [els.chipAnalyst, els.chipStrategist, els.chipCopywriter].forEach(chip => {
        chip.dataset.status = 'waiting';
        chip.querySelector('.agent-chip-status').textContent = 'Waiting';
    });
}

// ---- Review Panel ----
function populateReview() {
    if (!state.jobData) return;

    // Requirements tab
    const req = state.jobData.extracted_requirements;
    if (req) {
        let html = `
            <div class="review-item">
                <div class="review-item-label">Project Name</div>
                <div class="review-item-value">${escapeHtml(req.project_name || 'N/A')}</div>
            </div>
            <div class="review-item">
                <div class="review-item-label">Client</div>
                <div class="review-item-value">${escapeHtml(req.issuing_company || 'N/A')}</div>
            </div>
            <div class="review-item">
                <div class="review-item-label">Response Deadline</div>
                <div class="review-item-value">${escapeHtml(req.response_deadline || 'N/A')}</div>
            </div>
            <div class="review-item">
                <div class="review-item-label">Budget</div>
                <div class="review-item-value highlight">${escapeHtml(req.budget_currency)} ${formatNumber(req.budget_amount)}</div>
            </div>
            <div class="review-item">
                <div class="review-item-label">Scope Items (${(req.scope_items || []).length})</div>
                <div class="review-item-value">
                    ${(req.scope_items || []).map(item =>
                        `<div style="padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
                            <strong>${escapeHtml(item.item_name)}</strong> — Qty: ${item.quantity} (${escapeHtml(item.category)})<br>
                            <span style="color:var(--text-muted);font-size:12px">${escapeHtml(item.specifications || item.description)}</span>
                        </div>`
                    ).join('')}
                </div>
            </div>
        `;
        $('#tab-requirements').innerHTML = html;
    }

    // Pricing tab
    const pricing = state.jobData.pricing_strategy;
    if (pricing) {
        let html = `
            <table class="review-price-table">
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Qty</th>
                        <th style="text-align:right">Unit Price</th>
                        <th style="text-align:right">Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${(pricing.line_items || []).map(item => `
                        <tr>
                            <td>${escapeHtml(item.item_name)}</td>
                            <td>${item.quantity}</td>
                            <td style="text-align:right">₹${formatNumber(item.unit_price)}</td>
                            <td style="text-align:right">₹${formatNumber(item.total_price)}</td>
                        </tr>
                    `).join('')}
                    ${(pricing.value_adds || []).map(va => `
                        <tr>
                            <td>${escapeHtml(va.item_name)} <span class="value-add-tag">Free Value-Add</span></td>
                            <td>${va.quantity}</td>
                            <td style="text-align:right">INCLUDED</td>
                            <td style="text-align:right">INCLUDED</td>
                        </tr>
                    `).join('')}
                    <tr class="total-row">
                        <td colspan="3"><strong>Subtotal</strong></td>
                        <td style="text-align:right">₹${formatNumber(pricing.subtotal)}</td>
                    </tr>
                    <tr class="total-row">
                        <td colspan="3"><strong>GST (${(pricing.tax_rate * 100).toFixed(0)}%)</strong></td>
                        <td style="text-align:right">₹${formatNumber(pricing.tax_amount)}</td>
                    </tr>
                    <tr class="total-row">
                        <td colspan="3"><strong>TOTAL</strong></td>
                        <td style="text-align:right"><strong>₹${formatNumber(pricing.total)}</strong></td>
                    </tr>
                </tbody>
            </table>
        `;

        if (pricing.pricing_rationale) {
            html += `
                <div class="review-item">
                    <div class="review-item-label">Pricing Rationale</div>
                    <div class="review-item-value">${escapeHtml(pricing.pricing_rationale)}</div>
                </div>
            `;
        }

        if (pricing.competitor_analyses && pricing.competitor_analyses.length > 0) {
            html += `
                <div class="review-item">
                    <div class="review-item-label">Competitor Analysis</div>
                    <div class="review-item-value">
                        ${pricing.competitor_analyses.map(ca => `
                            <div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
                                <strong>${escapeHtml(ca.competitor_name)}</strong> — ${escapeHtml(ca.product_id)}<br>
                                ${ca.competitor_price > 0 ? `Their Price: ₹${formatNumber(ca.competitor_price)} | ` : ''}Our Price: ₹${formatNumber(ca.our_price)}<br>
                                <span style="color:var(--text-muted);font-size:12px">${escapeHtml(ca.recommendation)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        $('#tab-pricing').innerHTML = html;
    }

    // Proposal tab
    const proposal = state.jobData.proposal_draft;
    if (proposal) {
        let html = `
            <div class="review-item">
                <div class="review-item-label">Executive Summary</div>
                <div class="review-item-value">${escapeHtml(proposal.executive_summary || 'N/A')}</div>
            </div>
        `;

        if (proposal.technical_proposal) {
            proposal.technical_proposal.forEach(section => {
                html += `
                    <div class="review-item">
                        <div class="review-item-label">${escapeHtml(section.title)}</div>
                        <div class="review-item-value">${escapeHtml(section.content)}</div>
                    </div>
                `;
            });
        }

        html += `
            <div class="review-item">
                <div class="review-item-label">Value Proposition</div>
                <div class="review-item-value">${escapeHtml(proposal.value_proposition || 'N/A')}</div>
            </div>
            <div class="review-item">
                <div class="review-item-label">Support Plan</div>
                <div class="review-item-value">${escapeHtml(proposal.support_plan || 'N/A')}</div>
            </div>
        `;

        $('#tab-proposal').innerHTML = html;
    }
}

function switchTab(tabName) {
    $$('.review-tab').forEach(t => t.classList.remove('active'));
    $$('.review-tab-content').forEach(t => t.classList.remove('active'));

    $(`.review-tab[data-tab="${tabName}"]`).classList.add('active');
    $(`#tab-${tabName}`).classList.add('active');
}

// ---- Changes / Feedback ----
function addChange() {
    const agent = els.changeAgent.value;
    const instruction = els.changeInstruction.value.trim();
    if (!instruction) return;

    state.changes.push({ target_agent: agent, instruction, section: '' });
    renderChanges();
    els.changeInstruction.value = '';

    // Show submit changes button
    els.submitChangesBtn.style.display = 'inline-flex';
}

function removeChange(index) {
    state.changes.splice(index, 1);
    renderChanges();
    if (state.changes.length === 0) {
        els.submitChangesBtn.style.display = 'none';
    }
}

function renderChanges() {
    els.changesList.innerHTML = state.changes.map((c, i) => `
        <div class="change-item">
            <span class="change-item-agent">${c.target_agent}</span>
            <span class="change-item-text">${escapeHtml(c.instruction)}</span>
            <button class="change-item-remove" onclick="removeChange(${i})">✕</button>
        </div>
    `).join('');
}

async function approveProposal() {
    if (state.changes.length > 0) {
        if (!confirm('You have pending changes. Approve without submitting them?')) return;
    }

    els.approveBtn.disabled = true;
    els.approveBtn.innerHTML = '<span class="spinner"></span> Generating PDF...';
    setGlobalStatus('processing', 'Generating PDF...');

    // Show agent section for PDF generation messages
    showSection('agentSection');

    // Stream approval + PDF generation
    streamAgentFeed(`/api/approve/${state.jobId}`);
}

async function submitChanges() {
    if (state.changes.length === 0) return;

    els.submitChangesBtn.disabled = true;
    els.submitChangesBtn.innerHTML = '<span class="spinner"></span> Re-running Agents...';
    setGlobalStatus('processing', 'Revising...');

    // Hide review, show agent feed
    els.reviewSection.classList.add('hidden');
    showSection('agentSection');
    resetAgentChips();

    const feedback = {
        approved: false,
        changes: state.changes,
    };

    try {
        const postRes = await fetch(`/api/revise/${state.jobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(feedback),
        });
        if (!postRes.ok) {
            const err = await postRes.json().catch(() => ({}));
            throw new Error(err.detail || postRes.statusText || 'Failed to queue revision');
        }
    } catch (e) {
        console.error(e);
        setGlobalStatus('error', 'Could not submit revision');
        els.submitChangesBtn.disabled = false;
        els.submitChangesBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Submit Changes & Re-run Agents
    `;
        return;
    }

    streamAgentFeed(`/api/revise/${state.jobId}`);

    // Clear changes
    state.changes = [];
    renderChanges();
    els.submitChangesBtn.style.display = 'none';
    els.submitChangesBtn.disabled = false;
    els.submitChangesBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Submit Changes & Re-run Agents
    `;
}

// ==================================================
// ---- NEW RFP (Reset) ----
// ==================================================
function startNewRfp() {
    // Confirm if user is in the middle of something
    if (state.status === 'processing') {
        if (!confirm('An RFP is currently being processed. Start a new one anyway?')) return;
    }

    // Reset state
    state.jobId = null;
    state.status = 'idle';
    state.changes = [];
    state.jobData = null;
    state.uploadFile = null;
    state.inputMode = 'upload';

    // Reset global status
    setGlobalStatus('', 'Ready');

    // Reset input fields
    els.rfpInput.value = '';
    els.charCount.textContent = '0 characters';
    els.companyName.value = 'Ering Solutions';
    els.contactName.value = 'Sales Team';
    els.contactEmail.value = 'sales@eringsolutions.com';

    // Reset file upload
    els.fileInput.value = '';
    els.selectedFile.classList.add('hidden');
    els.dropZone.style.display = 'block';

    // Reset input mode to upload
    setInputMode('upload');

    // Reset process button
    els.processBtn.disabled = false;
    els.processBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        Process RFP with AI Agents
    `;

    // Reset approve button
    els.approveBtn.disabled = false;
    els.approveBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12"/>
        </svg>
        Approve &amp; Generate PDF
    `;

    // Reset submit changes button
    els.submitChangesBtn.style.display = 'none';
    els.submitChangesBtn.disabled = false;

    // Reset changes list
    els.changesList.innerHTML = '';

    // Clear review tabs
    $('#tab-requirements').innerHTML = '';
    $('#tab-pricing').innerHTML = '';
    $('#tab-proposal').innerHTML = '';

    // Reset agent chips
    resetAgentChips();

    // Clear feed
    clearFeed();
    els.feedContainer.innerHTML = `
        <div class="feed-empty">
            <div class="feed-empty-icon">🤖</div>
            <p>Agent reasoning will appear here in real-time...</p>
        </div>
    `;

    // Reset download button
    els.downloadPdfBtn.href = '#';
    els.downloadPdfBtn.removeAttribute('download');
    els.downloadPdfBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download PDF Quotation
    `;
    els.downloadMeta.textContent = 'Generated with AI-powered analysis';

    // Hide all sections except hero and input
    els.agentSection.classList.add('hidden');
    els.reviewSection.classList.add('hidden');
    els.downloadSection.classList.add('hidden');
    els.heroSection.style.display = '';
    els.inputSection.style.display = '';

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================================================
// ---- HISTORY ----
// ==================================================

function loadHistory() {
    try {
        const saved = localStorage.getItem('sme02_history');
        if (saved) {
            state.history = JSON.parse(saved);
        }
    } catch (e) {
        console.warn('Could not load history:', e);
        state.history = [];
    }
}

function saveHistory() {
    try {
        // Keep only last 50 entries
        if (state.history.length > 50) {
            state.history = state.history.slice(0, 50);
        }
        localStorage.setItem('sme02_history', JSON.stringify(state.history));
    } catch (e) {
        console.warn('Could not save history:', e);
    }
}

function addToHistory(entry) {
    // Check if already exists (by job_id)
    const existing = state.history.findIndex(h => h.job_id === entry.job_id);
    if (existing >= 0) {
        state.history[existing] = { ...state.history[existing], ...entry };
    } else {
        state.history.unshift(entry); // newest first
    }
    saveHistory();
}

function updateHistoryStatus(jobId, status) {
    const entry = state.history.find(h => h.job_id === jobId);
    if (entry) {
        entry.status = status;
        saveHistory();
    }
}

function updateHistoryMeta(jobId, meta) {
    const entry = state.history.find(h => h.job_id === jobId);
    if (entry) {
        Object.assign(entry, meta);
        saveHistory();
    }
}

function openHistory() {
    renderHistoryList();
    els.historyModal.classList.remove('hidden');
}

function closeHistory() {
    els.historyModal.classList.add('hidden');
}

function getStatusIcon(status) {
    const map = {
        'completed': '✅',
        'error': '❌',
        'processing': '⚙️',
        'analyzing': '🔍',
        'pricing': '📊',
        'drafting': '✍️',
        'awaiting_approval': '⏳',
        'revising': '🔄',
        'generating_pdf': '📄',
        'pending': '🕐',
    };
    return map[status] || '📋';
}

function getStatusCategory(status) {
    if (status === 'completed') return 'completed';
    if (status === 'error') return 'error';
    if (status === 'pending') return 'pending';
    return 'processing';
}

function renderHistoryList() {
    if (state.history.length === 0) {
        els.historyList.innerHTML = `
            <div class="history-empty">
                <div class="history-empty-icon">📋</div>
                <p>No previous RFPs yet. Process your first RFP to see it here.</p>
            </div>
        `;
        return;
    }

    els.historyList.innerHTML = state.history.map(entry => {
        const title = entry.project_name || `RFP Job ${entry.job_id.toUpperCase()}`;
        const time = entry.created_at ? new Date(entry.created_at).toLocaleString() : 'Unknown';
        const statusCat = getStatusCategory(entry.status);
        const statusIcon = getStatusIcon(entry.status);
        const statusLabel = (entry.status || 'unknown').replace(/_/g, ' ');

        let actionsHtml = '';
        if (entry.pdf_ready && entry.status === 'completed') {
            actionsHtml = `
                <div class="history-item-actions">
                    <a class="history-download-btn" href="/api/download-pdf/${entry.job_id}" download="SME02_Quotation_${entry.job_id}.pdf" title="Download PDF" onclick="event.stopPropagation()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="7 10 12 15 17 10"/>
                            <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                    </a>
                </div>
            `;
        }

        return `
            <div class="history-item" data-job-id="${entry.job_id}">
                <div class="history-item-icon ${statusCat}">${statusIcon}</div>
                <div class="history-item-body">
                    <div class="history-item-title">${escapeHtml(title)}</div>
                    <div class="history-item-meta">
                        <span>${entry.job_id.toUpperCase()}</span>
                        <span>•</span>
                        <span>${time}</span>
                    </div>
                </div>
                <span class="history-item-status ${entry.status}">${statusLabel}</span>
                ${actionsHtml}
            </div>
        `;
    }).join('');
}

// ---- Helpers ----
function showSection(sectionId) {
    const section = $(`#${sectionId}`);
    section.classList.remove('hidden');
    section.style.animation = 'none';
    section.offsetHeight; // Trigger reflow
    section.style.animation = '';
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setGlobalStatus(type, text) {
    els.globalStatus.className = `status-badge ${type}`;
    els.globalStatus.innerHTML = `<span class="status-dot"></span> ${text}`;
}

function formatNumber(num) {
    if (!num && num !== 0) return '0';
    return Number(num).toLocaleString('en-IN');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Make removeChange globally accessible
window.removeChange = removeChange;
