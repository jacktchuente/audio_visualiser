document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('uploadForm');
    const styleSelect = document.getElementById('styleSelect');
    const waveOptions = document.getElementById('waveOptions');
    const statusText = document.getElementById('statusText');
    const progressSection = document.getElementById('progress');
    const downloadLink = document.getElementById('downloadLink');

    // Toggle options based on style
    function updateVisibility() {
        if (styleSelect.value === 'wave') {
            waveOptions.style.display = '';
        } else {
            waveOptions.style.display = 'none';
        }
    }
    styleSelect.addEventListener('change', updateVisibility);
    updateVisibility();

    // Preset buttons
    document.getElementById('presetMinimal').addEventListener('click', () => {
        form.style.value = 'wave';
        form.resolution.value = '1280x720';
        form.fps.value = '25';
        form.mode.value = 'line';
        form.color.value = 'white';
        form.background.value = 'black';
        form.normalize.checked = false;
        updateVisibility();
    });
    document.getElementById('presetNeon').addEventListener('click', () => {
        form.style.value = 'wave';
        form.resolution.value = '1920x1080';
        form.fps.value = '30';
        form.mode.value = 'p2p';
        form.color.value = 'magenta';
        form.background.value = 'black';
        form.normalize.checked = false;
        updateVisibility();
    });
    document.getElementById('presetSpectrum').addEventListener('click', () => {
        form.style.value = 'spectrum';
        form.resolution.value = '1280x720';
        form.fps.value = '25';
        form.background.value = 'black';
        form.normalize.checked = false;
        updateVisibility();
    });

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const fd = new FormData(form);
        // Hide previous progress
        progressSection.style.display = 'none';
        downloadLink.style.display = 'none';
        statusText.textContent = 'Envoi du fichier…';
        progressSection.style.display = '';
        try {
            const resp = await fetch('/upload', {
                method: 'POST',
                body: fd,
            });
            if (!resp.ok) {
                const data = await resp.json();
                throw new Error(data.detail || 'Erreur serveur');
            }
            const data = await resp.json();
            const jobId = data.job_id;
            statusText.textContent = 'Job démarré. ID : ' + jobId;
            // Poll status
            const interval = setInterval(async () => {
                const res = await fetch('/status/' + jobId);
                if (!res.ok) {
                    clearInterval(interval);
                    statusText.textContent = 'Erreur lors de la récupération du statut';
                    return;
                }
                const job = await res.json();
                if (job.status === 'done') {
                    clearInterval(interval);
                    statusText.textContent = 'Rendu terminé !';
                    downloadLink.href = '/download/' + jobId;
                    downloadLink.style.display = '';
                } else if (job.status === 'error') {
                    clearInterval(interval);
                    statusText.textContent = 'Erreur : ' + job.error;
                } else {
                    statusText.textContent = 'Statut : ' + job.status;
                }
            }, 2000);
        } catch (err) {
            statusText.textContent = 'Erreur : ' + err.message;
        }
    });
});
