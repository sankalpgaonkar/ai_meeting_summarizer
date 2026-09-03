// AI Meeting Summarizer - Main Application JavaScript
// Uses native EventSource (no polyfill needed for modern browsers)

class MeetingSummarizer {
    constructor() {
        this.state = {
            recording: false,
            meetingId: null,
            startTime: null,
            timerInterval: null,
            volumeInterval: null,
            eventsource: null,
            currentView: 'home',
            processing: false,
        };

        this.init();
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            this.loadMeetings();
            this.connectSSE();
            this.setupVideoUpload();
            this.setupMicrophoneTest();
            this.setupEventListeners();
        });
    }

    setupEventListeners() {
        // Video file input
        const videoInput = document.getElementById('video-input');
        if (videoInput) {
            videoInput.addEventListener('change', (e) => this.handleVideoSelect(e.target));
        }

        // Video dropzone
        const dropzone = document.getElementById('video-dropzone');
        if (dropzone) {
            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('border-blue-400', 'bg-blue-50');
            });
            dropzone.addEventListener('dragleave', () => {
                dropzone.classList.remove('border-blue-400', 'bg-blue-50');
            });
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('border-blue-400', 'bg-blue-50');
                const file = e.dataTransfer.files[0];
                if (file) {
                    document.getElementById('video-input').files = e.dataTransfer.files;
                    this.handleVideoSelect(document.getElementById('video-input'));
                }
            });
            // Click to open file dialog
            dropzone.addEventListener('click', (e) => {
                if (e.target.tagName !== 'INPUT') {
                    document.getElementById('video-input').click();
                }
            });
        }
    }

    connectSSE() {
        if (this.state.eventsource) {
            this.state.eventsource.close();
        }

        try {
            // Use native EventSource (works in modern browsers)
            this.state.eventsource = new EventSource('/api/stream');

            this.state.eventsource.onopen = () => {
                document.getElementById('sse-dot').className = 'w-2 h-2 rounded-full bg-green-500';
                document.getElementById('sse-label').textContent = 'Live';
            };

            this.state.eventsource.onerror = () => {
                document.getElementById('sse-dot').className = 'w-2 h-2 rounded-full bg-red-500';
                document.getElementById('sse-label').textContent = 'Reconnecting...';
                setTimeout(() => this.connectSSE(), 3000);
            };

            this.setupSSEEventHandlers();

        } catch (error) {
            console.error('Failed to connect to SSE:', error);
            toast('Connection failed', 'error');
            setTimeout(() => this.connectSSE(), 5000);
        }
    }

    setupSSEEventHandlers() {
        const safeParse = (str) => {
            try { return JSON.parse(str); } catch (e) { return {}; }
        };

        this.state.eventsource.addEventListener('recording_started', (e) => {
            const data = safeParse(e.data);
            if (data.meeting_id) this.setState({ meetingId: data.meeting_id });
            toast('Recording started', 'success');
        });

        this.state.eventsource.addEventListener('partial_transcript', (e) => {
            const data = safeParse(e.data);
            const el = document.getElementById('live-transcript');
            if (el) {
                const text = data.text || '';
                el.innerHTML = text ? `<p>${this.escapeHtml(text)}</p>` : '<span class="text-slate-400 italic">Listening...</span>';
                el.scrollTop = el.scrollHeight;
            }
        });

        this.state.eventsource.addEventListener('video_upload_started', (e) => {
            this.showProcessing('Uploading Video', 'Uploading file to server...');
            this.updateProcessing('Uploading file...', 10);
        });

        this.state.eventsource.addEventListener('video_upload_complete', (e) => {
            this.updateProcessing('Video saved, preparing transcription...', 25);
        });

        this.state.eventsource.addEventListener('processing_started', (e) => {
            this.showProcessing('Processing Meeting', 'Initializing transcription...');
            const el = document.getElementById('live-transcript-section');
            if (el) el.style.display = 'none';
            this.updateProcessing('Transcribing audio with Whisper...', 35);
        });

        this.state.eventsource.addEventListener('transcription_started', (e) => {
            this.showProcessing('Processing Meeting', 'Transcribing audio with Whisper...');
            this.updateProcessing('Transcribing audio with Whisper...', 45);
        });

        this.state.eventsource.addEventListener('transcription_complete', (e) => {
            this.updateProcessing('Analyzing content with Gemini AI...', 75);
        });

        this.state.eventsource.addEventListener('analysis_started', (e) => {
            this.updateProcessing('Generating Minutes of Meeting & Action Items...', 85);
        });

        this.state.eventsource.addEventListener('processing_complete', (e) => {
            const data = safeParse(e.data);
            this.stopPolling();
            this.updateProcessing('Done! Loading summary...', 100);
            setTimeout(() => {
                this.hideProcessing();
                this.loadMeetings();
                if (data.meeting_id) this.showMeetingDetail(data.meeting_id);
            }, 800);
        });

        this.state.eventsource.addEventListener('processing_error', (e) => {
            const data = safeParse(e.data);
            this.stopPolling();
            this.hideProcessing();
            toast('Processing error: ' + (data.error || 'Unknown error'), 'error');
        });

        this.state.eventsource.onmessage = (e) => {
            if (!e.data || e.data === ': keepalive') return;
        };
    }

    async loadMeetings(page = 1) {
        try {
            const response = await fetch(`/api/meetings?page=${page}`);
            const data = await response.json();
            this.renderMeetings(data.meetings, data.total);
        } catch (error) {
            toast('Failed to load meetings', 'error');
        }
    }

    renderMeetings(meetings, total) {
        document.getElementById('meetings-count').textContent = total ? `${total} total` : '';
        const el = document.getElementById('meetings-list');

        if (!meetings || meetings.length === 0) {
            el.innerHTML = this.getEmptyMeetingsHTML();
            return;
        }

        el.innerHTML = meetings.map(m => this.getMeetingCardHTML(m)).join('');
    }

    getEmptyMeetingsHTML() {
        return `<div class="text-center py-12 text-slate-400">
                    <svg class="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                    </svg>
                    <p class="text-sm">No meetings yet. Start recording!</p>
                </div>`;
    }

    getMeetingCardHTML(meeting) {
        const sentimentColor = {
            'positive': 'bg-emerald-100 text-emerald-700',
            'negative': 'bg-red-100 text-red-700',
            'neutral': 'bg-slate-100 text-slate-600'
        };

        const statusBadge = {
            'complete': '<span class="bg-emerald-100 text-emerald-700 text-xs px-2 py-0.5 rounded-full font-medium">Complete</span>',
            'processing': '<span class="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-medium">Processing</span>',
            'error': '<span class="bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-medium">Error</span>',
            'pending': '<span class="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">Pending</span>',
            'recording': '<span class="bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-medium d-flex align-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-red-500 pulse-recording"></span>Recording</span>'
        };

        const date = new Date(meeting.created_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        const actionCount = (meeting.action_items || []).length;

        return `<div class="bg-white rounded-xl shadow-sm p-5 card-hover cursor-pointer border border-slate-100" onclick="app.showMeetingDetail('${meeting.id}')">
                    <div class="d-flex justify-between align-center mb-2">
                        <h4 class="font-semibold text-slate-800 truncate flex-1">${this.escapeHtml(meeting.title)}</h4>
                        ${statusBadge[meeting.status] || statusBadge['pending']}
                    </div>
                    <p class="text-sm text-slate-500 mb-3 line-clamp-2">${meeting.summary ? this.escapeHtml(meeting.summary) : (meeting.transcript ? this.escapeHtml(meeting.transcript.substring(0, 150)) + '...' : 'No content yet')}</p>
                    <div class="d-flex justify-between align-center text-xs text-slate-400">
                        <span>${date}</span>
                        <div class="d-flex align-center gap-3">
                            ${meeting.duration_seconds ? `<span>${this.formatDuration(meeting.duration_seconds)}</span>` : ''}
                            ${meeting.source === 'video' ? '<span class="d-flex align-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>Video</span>' : ''}
                            ${actionCount ? `<span>${actionCount} action items</span>` : ''}
                            ${meeting.sentiment ? `<span class="${sentimentColor[meeting.sentiment] || sentimentColor.neutral} text-xs px-1.5 py-0.5 rounded font-medium">${meeting.sentiment}</span>` : ''}
                        </div>
                    </div>
                </div>`;
    }

    async showMeetingDetail(id) {
        try {
            const response = await fetch(`/api/meetings/${id}`);
            const meeting = await response.json();

            this.setState({ currentView: 'detail' });
            document.getElementById('view-home').style.display = 'none';
            document.getElementById('view-detail').style.display = 'block';

            const sentimentColors = {
                'positive': 'bg-emerald-100 text-emerald-700',
                'negative': 'bg-red-100 text-red-700',
                'neutral': 'bg-slate-100 text-slate-600'
            };

            document.getElementById('detail-content').innerHTML = `
                <div class="bg-white rounded-2xl shadow-lg overflow-hidden">
                    <div class="bg-gradient-to-r from-blue-600 to-indigo-600 p-6 text-white">
                        <div class="d-flex justify-between align-center">
                            <div>
                                <h2 class="text-2xl font-bold">${this.escapeHtml(meeting.title)}</h2>
                                <p class="text-blue-200 text-sm mt-1">${new Date(meeting.created_at).toLocaleDateString('en-US', {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'})}</p>
                            </div>
                            <div class="d-flex gap-2">
                                <a href="/api/export/${meeting.id}" class="bg-white/20 hover:bg-white/30 text-white text-sm font-medium py-2 px-4 rounded-lg transition">Export MD</a>
                                <button onclick="app.deleteMeeting('${meeting.id}')" class="bg-white/20 hover:bg-white/30 text-white text-sm font-medium py-2 px-4 rounded-lg transition">Delete</button>
                            </div>
                        </div>
                        <div class="d-flex gap-4 mt-4">
                            ${meeting.duration_seconds ? `<span class="text-sm text-blue-200">Duration: ${this.formatDuration(meeting.duration_seconds)}</span>` : ''}
                            <span class="text-sm text-blue-200">Source: ${meeting.source}</span>
                            ${meeting.sentiment ? `<span class="${sentimentColors[meeting.sentiment]} text-xs px-2 py-0.5 rounded-full font-medium">${meeting.sentiment}</span>` : ''}
                        </div>
                    </div>
                    <div class="p-6">
                        ${meeting.summary ? `<div class="mb-6">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Summary</h3>
                            <p class="text-slate-600 leading-relaxed">${this.escapeHtml(meeting.summary)}</p>
                        </div>` : ''}
                        ${meeting.key_points && meeting.key_points.length ? `<div class="mb-6">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Key Points</h3>
                            <ul class="space-y-1">${meeting.key_points.map(p => `<li class="text-slate-600 text-sm d-flex gap-2"><span class="text-blue-500 mt-1 shrink-0">•</span>${this.escapeHtml(p)}</li>`).join('')}</ul>
                        </div>` : ''}
                        ${meeting.action_items && meeting.action_items.length ? `<div class="mb-6">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Action Items</h3>
                            <div class="space-y-2">${meeting.action_items.map(a => `<div class="bg-amber-50 border border-amber-200 rounded-lg p-3">
                                <div class="d-flex justify-between align-center">
                                    <span class="text-slate-700 text-sm font-medium">${this.escapeHtml(a.task)}</span>
                                    ${a.owner ? `<span class="text-xs bg-amber-200 text-amber-800 px-2 py-0.5 rounded-full">${this.escapeHtml(a.owner)}</span>` : ''}
                                </div>
                                ${a.due ? `<p class="text-xs text-amber-600 mt-1">Due: ${this.escapeHtml(a.due)}</p>` : ''}
                            </div>`).join('')}</div>
                        </div>` : ''}
                        ${meeting.decisions && meeting.decisions.length ? `<div class="mb-6">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Decisions</h3>
                            <ul class="space-y-1">${meeting.decisions.map(d => `<li class="text-slate-600 text-sm d-flex gap-2"><span class="text-emerald-500 mt-1 shrink-0">✓</span>${this.escapeHtml(d)}</li>`).join('')}</ul>
                        </div>` : ''}
                        ${meeting.next_steps && meeting.next_steps.length ? `<div class="mb-6">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Next Steps</h3>
                            <ul class="space-y-1">${meeting.next_steps.map(s => `<li class="text-slate-600 text-sm d-flex gap-2"><span class="text-blue-500 mt-1 shrink-0">→</span>${this.escapeHtml(s)}</li>`).join('')}</ul>
                        </div>` : ''}
                        ${meeting.transcript ? `<div class="mt-6 pt-6 border-t border-slate-200">
                            <h3 class="text-lg font-semibold text-slate-700 mb-2">Full Transcript</h3>
                            <div class="bg-slate-50 rounded-lg p-4 max-h-96 overflow-y-auto scrollbar-thin">
                                <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">${this.escapeHtml(meeting.transcript)}</p>
                            </div>
                        </div>` : ''}
                    </div>
                </div>
            `;
        } catch (error) {
            toast('Failed to load meeting', 'error');
        }
    }

    showHome() {
        this.setState({ currentView: 'home' });
        document.getElementById('view-home').style.display = 'block';
        document.getElementById('view-detail').style.display = 'none';
        this.loadMeetings();
    }

    async deleteMeeting(id) {
        if (!confirm('Delete this meeting?')) return;

        try {
            const response = await fetch(`/api/meetings/${id}`, { method: 'DELETE' });
            toast('Meeting deleted', 'success');
            this.showHome();
        } catch (error) {
            toast('Failed to delete', 'error');
        }
    }

    async startRecording() {
        const title = document.getElementById('meeting-title').value;

        document.getElementById('btn-start').disabled = true;
        document.getElementById('btn-start').style.opacity = '0.5';

        try {
            const response = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: title || undefined }),
            });

            const data = await response.json();

            if (data.status === 'started') {
                this.setState({
                    recording: true,
                    meetingId: data.meeting_id,
                    startTime: Date.now()
                });

                document.getElementById('btn-stop').disabled = false;
                document.getElementById('btn-stop').style.opacity = '1';
                document.getElementById('btn-stop').classList.remove('cursor-not-allowed');
                document.getElementById('recording-info').style.display = 'flex';
                document.getElementById('volume-meter-container').style.display = 'block';
                document.getElementById('live-transcript-section').style.display = 'block';
                document.getElementById('live-transcript').innerHTML = '<span class="text-slate-400 italic">Listening for speech...</span>';

                this.startTimer();
                this.startVolumePolling();

                toast('Recording started', 'success');
            } else {
                toast('Failed to start: ' + JSON.stringify(data), 'error');
                document.getElementById('btn-start').disabled = false;
                document.getElementById('btn-start').style.opacity = '1';
            }
        } catch (error) {
            toast('Failed to start recording', 'error');
            document.getElementById('btn-start').disabled = false;
            document.getElementById('btn-start').style.opacity = '1';
        }
    }

    async stopRecording() {
        if (!this.state.recording) return;

        document.getElementById('btn-stop').disabled = true;
        document.getElementById('btn-stop').style.opacity = '0.5';

        try {
            const response = await fetch('/api/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ meeting_id: this.state.meetingId }),
            });

            const data = await response.json();

            this.setState({ recording: false });
            this.stopTimer();
            this.stopVolumePolling();

            document.getElementById('btn-start').disabled = false;
            document.getElementById('btn-start').style.opacity = '1';
            document.getElementById('btn-stop').disabled = true;
            document.getElementById('btn-stop').style.opacity = '0.5';
            document.getElementById('btn-stop').classList.add('cursor-not-allowed');
            document.getElementById('recording-info').style.display = 'none';
            document.getElementById('volume-meter-container').style.display = 'none';
            document.getElementById('volume-bar').style.width = '0%';
            document.getElementById('meeting-title').value = '';

            toast('Processing meeting...', 'info');
        } catch (error) {
            toast('Failed to stop recording', 'error');
        }
    }

    startTimer() {
        this.stopTimer();
        this.state.timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.state.startTime) / 1000);
            document.getElementById('recording-timer').textContent = this.formatTime(elapsed);
        }, 1000);
    }

    stopTimer() {
        if (this.state.timerInterval) {
            clearInterval(this.state.timerInterval);
            this.state.timerInterval = null;
        }
    }

    startVolumePolling() {
        this.stopVolumePolling();
        this.state.volumeInterval = setInterval(async () => {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                const vol = data.audio.last_volume || 0;
                const pct = Math.min(vol * 300, 100);
                const bar = document.getElementById('volume-bar');
                bar.style.width = pct + '%';
                bar.style.backgroundColor = pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#22c55e';
                document.getElementById('volume-value').textContent = Math.round(pct) + '%';
                document.getElementById('chunk-count').textContent = (data.audio.chunk_count || 0) + ' chunks';
            } catch (error) {
                // Silent fail for polling errors
            }
        }, 200);
    }

    stopVolumePolling() {
        if (this.state.volumeInterval) {
            clearInterval(this.state.volumeInterval);
            this.state.volumeInterval = null;
        }
    }

    setupMicrophoneTest() {
        // No setup needed - test is handled by inline onclick
    }

    setupVideoUpload() {
        const form = document.getElementById('video-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.uploadVideo();
            });
        }
    }

    async uploadVideo() {
        const form = document.getElementById('video-form');
        const formData = new FormData(form);
        const btn = document.getElementById('btn-upload');

        btn.disabled = true;
        btn.innerHTML = '<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> Uploading...';

        this.showProcessing('Uploading Video', 'Uploading file to server...');
        this.updateProcessing('Uploading file...', 15);

        try {
            const response = await fetch('/api/upload_video', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            btn.disabled = false;
            btn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg> Analyze Video';

            if (data.error) {
                toast(data.error, 'error');
                this.hideProcessing();
            } else {
                this.clearVideo();
                this.loadMeetings();
                toast('Video uploaded! Transcribing & analyzing...', 'info');
                this.updateProcessing('Transcribing audio with Whisper...', 35);
                if (data.meeting_id) {
                    this.startPolling(data.meeting_id);
                }
            }
        } catch (error) {
            toast('Upload failed: ' + error.message, 'error');
            this.hideProcessing();
            btn.disabled = false;
            btn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg> Analyze Video';
        }
    }

    startPolling(meetingId) {
        this.stopPolling();
        let attempts = 0;
        this.state.pollInterval = setInterval(async () => {
            attempts++;
            if (attempts > 120) { // 4 minutes timeout
                this.stopPolling();
                return;
            }
            try {
                const response = await fetch(`/api/meetings/${meetingId}`);
                if (!response.ok) return;
                const meeting = await response.json();

                if (meeting.status === 'complete') {
                    this.stopPolling();
                    this.updateProcessing('Done! Loading summary...', 100);
                    setTimeout(() => {
                        this.hideProcessing();
                        this.loadMeetings();
                        this.showMeetingDetail(meetingId);
                    }, 500);
                } else if (meeting.status === 'error' || meeting.status === 'no_speech' || meeting.status === 'empty') {
                    this.stopPolling();
                    this.hideProcessing();
                    this.loadMeetings();
                    this.showMeetingDetail(meetingId);
                } else if (meeting.status === 'transcribed') {
                    this.updateProcessing('Generating summary with Gemini AI...', 70);
                } else if (meeting.status === 'processing_video' || meeting.status === 'uploading') {
                    this.updateProcessing('Transcribing audio with Whisper...', Math.min(30 + attempts * 2, 65));
                }
            } catch (e) {
                // Ignore polling errors
            }
        }, 2000);
    }

    stopPolling() {
        if (this.state.pollInterval) {
            clearInterval(this.state.pollInterval);
            this.state.pollInterval = null;
        }
    }

    handleVideoSelect(input) {
        const file = input.files[0];
        if (!file) return;

        document.getElementById('video-label').textContent = file.name;
        document.getElementById('video-preview').classList.remove('hidden');
        document.getElementById('video-filename').textContent = file.name;
        document.getElementById('btn-upload').style.display = 'flex';
    }

    clearVideo() {
        document.getElementById('video-input').value = '';
        document.getElementById('video-label').textContent = 'Drop video here or click to browse';
        document.getElementById('video-preview').classList.add('hidden');
        document.getElementById('btn-upload').style.display = 'none';
    }

    showProcessing(title, status) {
        document.getElementById('processing-title').textContent = title;
        document.getElementById('processing-status').textContent = status;
        document.getElementById('processing-bar').style.width = '0%';
        document.getElementById('processing-section').style.display = 'block';
        document.getElementById('processing-section').scrollIntoView({ behavior: 'smooth' });
    }

    updateProcessing(status, pct) {
        document.getElementById('processing-status').textContent = status;
        document.getElementById('processing-bar').style.width = pct + '%';
    }

    hideProcessing() {
        document.getElementById('processing-section').style.display = 'none';
    }

    setState(newState) {
        this.state = { ...this.state, ...newState };
    }

    toast(msg, type = 'info') {
        const colors = {
            success: 'bg-emerald-500',
            error: 'bg-red-500',
            warning: 'bg-amber-500',
            info: 'bg-blue-500'
        };

        const icons = {
            success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
            error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>',
            warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
            info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        };

        const el = document.createElement('div');
        el.className = `toast-enter d-flex align-center gap-2 ${colors[type] || colors.info} text-white px-4 py-3 rounded-xl shadow-xl text-sm font-medium`;
        el.style.pointerEvents = 'auto';
        el.innerHTML = icons[type] + '<span>' + this.escapeHtml(msg) + '</span>';
        document.getElementById('toast-container').appendChild(el);

        setTimeout(() => {
            el.classList.remove('toast-enter');
            el.classList.add('toast-exit');
            setTimeout(() => el.remove(), 300);
        }, 4000);
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    formatDuration(seconds) {
        if (!seconds) return '0s';
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
    }

    formatTime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        if (hours > 0) {
            return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        }
        return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
}

// Initialize the app when the page loads
const app = new MeetingSummarizer();

// Expose functions for inline onclick handlers in template
// This is needed because the template uses onclick="functionName()"
window.app = app;
window.loadMeetings = () => app.loadMeetings();
window.connectSSE = () => app.connectSSE();
window.testMicrophone = () => {
    toast('Testing microphone (3 seconds)...', 'info');
    fetch('/api/mic-test', {method: 'POST', headers: {'Content-Type': 'application/json'}})
        .then(r => r.json())
        .then(data => {
            if (data.error) { toast('Mic test failed: ' + data.error, 'error'); return; }
            const msgs = {good: 'Mic is working great!', low: 'Mic level is low. Move closer.', high: 'Mic is loud. Reduce volume.', silent: 'No audio detected. Check mic.'};
            const types = {good: 'success', low: 'warning', high: 'warning', silent: 'error'};
            toast(`${msgs[data.quality]} (Volume: ${Math.round(data.volume * 100)}%)`, types[data.quality] || 'info');
        })
        .catch(() => toast('Mic test failed', 'error'));
};
window.startRecording = () => app.startRecording();
window.stopRecording = () => app.stopRecording();
window.handleVideoSelect = (input) => app.handleVideoSelect(input);
window.uploadVideo = (e) => {
    if (e) e.preventDefault();
    app.uploadVideo();
};
window.clearVideo = () => app.clearVideo();
window.deleteMeeting = (id) => app.deleteMeeting(id);
window.showMeetingDetail = (id) => app.showMeetingDetail(id);
window.showHome = () => app.showHome();
