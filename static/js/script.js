(function () {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  const dropzoneContent = document.getElementById('dropzoneContent');
  const previewContent = document.getElementById('previewContent');
  const previewImage = document.getElementById('previewImage');
  const changeFileBtn = document.getElementById('changeFileBtn');
  const extractBtn = document.getElementById('extractBtn');
  const uploadError = document.getElementById('uploadError');

  const emptyState = document.getElementById('emptyState');
  const processingState = document.getElementById('processingState');
  const fieldsState = document.getElementById('fieldsState');
  const copyBtn = document.getElementById('copyBtn');
  const copiedBadge = document.getElementById('copiedBadge');
  const resetBtn = document.getElementById('resetBtn');

  const ALLOWED_TYPES = ['image/png', 'image/jpeg'];
  let selectedFile = null;
  let lastResult = null;

  function showUploadError(message) {
    uploadError.textContent = message;
    uploadError.hidden = !message;
  }

  function resetResultsPanel() {
    emptyState.hidden = false;
    processingState.hidden = true;
    fieldsState.hidden = true;
    copyBtn.hidden = true;
    copiedBadge.hidden = true;
    resetBtn.hidden = true;
    lastResult = null;
  }

  function selectFile(file) {
    showUploadError('');

    if (!file) return;

    if (!ALLOWED_TYPES.includes(file.type)) {
      showUploadError('Unsupported file type. Please upload a PNG or JPG image.');
      return;
    }

    selectedFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
      previewImage.src = e.target.result;
      dropzoneContent.hidden = true;
      previewContent.hidden = false;
      extractBtn.disabled = false;
    };
    reader.readAsDataURL(file);

    resetResultsPanel();
  }

  dropzone.addEventListener('click', (e) => {
    if (e.target === changeFileBtn) return;
    if (!previewContent.hidden) return;
    fileInput.click();
  });

  changeFileBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      selectFile(e.target.files[0]);
    }
  });

  ['dragenter', 'dragover'].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) selectFile(file);
  });

  function setField(elId, value) {
    const el = document.getElementById(elId);
    if (value) {
      el.textContent = value;
      el.classList.remove('not-detected');
    } else {
      el.textContent = 'Not detected';
      el.classList.add('not-detected');
    }
  }

  async function extractDetails() {
    if (!selectedFile) return;

    showUploadError('');
    emptyState.hidden = true;
    fieldsState.hidden = true;
    copyBtn.hidden = true;
    copiedBadge.hidden = true;
    resetBtn.hidden = true;
    processingState.hidden = false;
    extractBtn.disabled = true;

    const formData = new FormData();
    formData.append('receipt', selectedFile);

    try {
      const response = await fetch('/extract', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to process the receipt.');
      }

      lastResult = data.fields;

      setField('fieldName', data.fields.name);
      setField('fieldMobile', data.fields.mobile_number);
      setField('fieldReference', data.fields.reference_number);
      setField('fieldDate', data.fields.date);
      setField('fieldTime', data.fields.time);
      setField('fieldAmount', data.fields.total_amount);

      processingState.hidden = true;
      fieldsState.hidden = false;
      copyBtn.hidden = false;
      resetBtn.hidden = false;
    } catch (err) {
      processingState.hidden = true;
      emptyState.hidden = false;
      showUploadError(err.message || 'Something went wrong while processing the receipt.');
    } finally {
      extractBtn.disabled = false;
    }
  }

  extractBtn.addEventListener('click', extractDetails);

  copyBtn.addEventListener('click', async () => {
    if (!lastResult) return;

    const text = [
      `Name: ${lastResult.name || 'Not detected'}`,
      `Mobile Number: ${lastResult.mobile_number || 'Not detected'}`,
      `Reference Number: ${lastResult.reference_number || 'Not detected'}`,
      `Date: ${lastResult.date || 'Not detected'}`,
      `Time: ${lastResult.time || 'Not detected'}`,
      `Total Amount Sent: ${lastResult.total_amount || 'Not detected'}`,
    ].join('\n');

    try {
      await navigator.clipboard.writeText(text);
      copiedBadge.hidden = false;
      setTimeout(() => { copiedBadge.hidden = true; }, 2000);
    } catch (err) {
      showUploadError('Could not copy to clipboard.');
    }
  });

  resetBtn.addEventListener('click', () => {
    selectedFile = null;
    fileInput.value = '';
    previewImage.src = '';
    dropzoneContent.hidden = false;
    previewContent.hidden = true;
    extractBtn.disabled = true;
    showUploadError('');
    resetResultsPanel();
  });
})();
