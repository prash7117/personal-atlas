/*
 * Copyright (c) 2026 Prashanth Shankar Narayan
 * SPDX-License-Identifier: Apache-2.0
 */

const GROUP_NAME_MAX = 80;
const GROUP_REPO_PREVIEW_LIMIT = 50; // change this to show more/less repo names

const groupUiState = {
    creating: false,
    editingId: null,
};

function getState() {
    if (typeof state !== 'undefined' && state) {
        return state;
    }
    return { repos: [], repoGroups: [] };
}

function getRepoLabel(repo) {
    if (!repo) {
        return '';
    }
    if (typeof displayNameFor === 'function') {
        return displayNameFor(repo);
    }
    const raw = repo.display_name || repo.repo_id || '';
    return raw.trim();
}

function repoLabelForId(repoId) {
    if (!repoId) {
        return '';
    }
    const current = getState();
    const repos = Array.isArray(current.repos) ? current.repos : [];
    const match = repos.find((repo) => repo.repo_id === repoId);
    if (match) {
        return getRepoLabel(match) || repoId;
    }
    return repoId;
}

function sortedRepos() {
    const current = getState();
    const repos = Array.isArray(current.repos) ? current.repos.slice() : [];
    repos.sort((a, b) => {
        const labelA = getRepoLabel(a).toLowerCase();
        const labelB = getRepoLabel(b).toLowerCase();
        if (labelA < labelB) return -1;
        if (labelA > labelB) return 1;
        return 0;
    });
    return repos;
}

function isGroupNameTaken(name, excludeName) {
    const target = (name || '').trim().toLowerCase();
    if (!target) {
        return false;
    }
    const current = getState();
    const groups = Array.isArray(current.repoGroups) ? current.repoGroups : [];
    return groups.some((group) => {
        const groupName = (group.name || '').trim().toLowerCase();
        if (!groupName) {
            return false;
        }
        if (excludeName && groupName === excludeName.trim().toLowerCase()) {
            return false;
        }
        return groupName === target;
    });
}

function setsEqual(setA, listB) {
    const list = Array.isArray(listB) ? listB : [];
    if (setA.size !== list.length) {
        return false;
    }
    for (let i = 0; i < list.length; i += 1) {
        if (!setA.has(list[i])) {
            return false;
        }
    }
    return true;
}

function buildRepoChecklist(container, selectedSet, filterValue, onChange) {
    container.innerHTML = '';
    const repos = sortedRepos();
    const filter = (filterValue || '').trim().toLowerCase();
    let visible = 0;

    repos.forEach((repo) => {
        const repoId = repo.repo_id || '';
        if (!repoId) {
            return;
        }
        const labelText = getRepoLabel(repo) || repoId;
        const hay = `${labelText} ${repoId}`.toLowerCase();
        if (filter && hay.indexOf(filter) === -1) {
            return;
        }
        visible += 1;
        const label = document.createElement('label');
        label.className = 'select-item';
        label.title = repoId;
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selectedSet.has(repoId);
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                selectedSet.add(repoId);
            } else {
                selectedSet.delete(repoId);
            }
            onChange();
        });
        const text = document.createElement('span');
        text.className = 'select-label';
        text.textContent = labelText;
        const meta = document.createElement('span');
        meta.className = 'select-meta';
        meta.textContent = labelText !== repoId ? repoId : '';
        if (!meta.textContent) {
            meta.style.display = 'none';
        }
        label.appendChild(checkbox);
        label.appendChild(text);
        label.appendChild(meta);
        container.appendChild(label);
    });

    if (!visible) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.textContent = filter ? 'No repos match this filter.' : 'No repos available.';
        container.appendChild(empty);
    }
}

function buildGroupRow(group) {
    const row = document.createElement('div');
    row.className = 'group-row';

    const main = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'group-title';
    title.textContent = group.name || '';
    main.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'group-meta';
    const repoIds = Array.isArray(group.repo_ids) ? group.repo_ids : [];
    const repoLabels = repoIds.map((repoId) => repoLabelForId(repoId));
    const previewLimit = GROUP_REPO_PREVIEW_LIMIT;
    const preview = repoLabels.slice(0, previewLimit).filter(Boolean).join(', ');
    const extra = repoLabels.length > previewLimit
        ? ` +${repoLabels.length - previewLimit}`
        : '';
    meta.textContent = repoIds.length
        ? `${repoIds.length} repos • ${preview}${extra}`
        : '0 repos';
    meta.title = repoLabels.join(', ');

    const actions = document.createElement('div');
    actions.className = 'group-actions';

    const editBtn = document.createElement('button');
    editBtn.className = 'ghost action';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => {
        groupUiState.editingId = group.name;
        groupUiState.creating = false;
        renderRepoGroupsManager();
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'ghost action danger';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', () => {
        handleDeleteGroup(group);
    });

    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);

    row.appendChild(main);
    row.appendChild(meta);
    row.appendChild(actions);

    return row;
}

function validateGroupInputs(name, selectedSet, mode, currentName) {
    const trimmedName = (name || '').trim();
    if (!trimmedName) {
        return 'Group name is required.';
    }
    if (trimmedName.indexOf('::') !== -1) {
        return 'Group name cannot contain "::".';
    }
    if (trimmedName.length > GROUP_NAME_MAX) {
        return `Group name must be ${GROUP_NAME_MAX} characters or fewer.`;
    }

    if (mode === 'create') {
        if (isGroupNameTaken(trimmedName, null)) {
            return 'Group name is already in use.';
        }
    } else if (currentName && trimmedName.toLowerCase() !== currentName.toLowerCase()) {
        if (isGroupNameTaken(trimmedName, currentName)) {
            return 'Group name is already in use.';
        }
    }

    if (!selectedSet.size) {
        return 'Select at least one repo.';
    }
    return '';
}

function buildGroupEditor(mode, group) {
    const wrapper = document.createElement('div');
    wrapper.className = 'group-editor';

    const fields = document.createElement('div');
    fields.className = 'group-fields';

    const nameLabel = document.createElement('label');
    nameLabel.textContent = 'Group name';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = group ? group.name || '' : '';
    nameInput.maxLength = GROUP_NAME_MAX;
    nameLabel.appendChild(nameInput);
    fields.appendChild(nameLabel);

    wrapper.appendChild(fields);

    const repoSection = document.createElement('div');
    const repoHeader = document.createElement('div');
    repoHeader.className = 'section-title';
    repoHeader.textContent = 'Repos';
    const repoFilter = document.createElement('input');
    repoFilter.type = 'text';
    repoFilter.placeholder = 'Filter repos...';

    const repoList = document.createElement('div');
    repoList.className = 'select-list group-repo-list';

    const selectedCount = document.createElement('div');
    selectedCount.className = 'group-helper';

    repoSection.appendChild(repoHeader);
    repoSection.appendChild(repoFilter);
    repoSection.appendChild(repoList);
    repoSection.appendChild(selectedCount);
    wrapper.appendChild(repoSection);

    const errorEl = document.createElement('div');
    errorEl.className = 'group-error';
    wrapper.appendChild(errorEl);

    const actions = document.createElement('div');
    actions.className = 'group-actions';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'primary action';
    saveBtn.textContent = mode === 'create' ? 'Create' : 'Save';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'ghost action';
    cancelBtn.textContent = 'Cancel';
    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);
    wrapper.appendChild(actions);

    const originalName = group ? group.name || '' : '';
    const originalRepoIds = group ? group.repo_ids || [] : [];
    const selectedSet = new Set(originalRepoIds);

    const updateSelectedCount = () => {
        selectedCount.textContent = `${selectedSet.size} selected`;
    };

    const updateState = () => {
        const errorMsg = validateGroupInputs(
            nameInput.value,
            selectedSet,
            mode,
            group ? group.name : null
        );
        errorEl.textContent = errorMsg;
        let changed = mode === 'create';
        if (mode !== 'create') {
            const nameChanged = nameInput.value.trim() !== originalName.trim();
            const reposChanged = !setsEqual(selectedSet, originalRepoIds);
            changed = nameChanged || reposChanged;
        }
        saveBtn.disabled = Boolean(errorMsg) || !changed;
        updateSelectedCount();
    };

    const refreshRepoList = () => {
        buildRepoChecklist(repoList, selectedSet, repoFilter.value, updateState);
        updateState();
    };

    nameInput.addEventListener('input', updateState);

    repoFilter.addEventListener('input', refreshRepoList);

    saveBtn.addEventListener('click', async () => {
        const payload = {
            name: nameInput.value.trim(),
            repo_ids: Array.from(selectedSet),
        };
        saveBtn.disabled = true;
        cancelBtn.disabled = true;
        try {
            if (mode === 'create') {
                await fetchJSON('/api/repo-groups', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } else {
                await fetchJSON(`/api/repo-groups/${encodeURIComponent(group.name)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            }
            groupUiState.creating = false;
            groupUiState.editingId = null;
            if (typeof loadRepoGroups === 'function') {
                await loadRepoGroups();
            }
            renderRepoGroupsManager();
        } catch (err) {
            errorEl.textContent = `Error: ${err.message}`;
            saveBtn.disabled = false;
            cancelBtn.disabled = false;
        }
    });

    cancelBtn.addEventListener('click', () => {
        groupUiState.creating = false;
        groupUiState.editingId = null;
        renderRepoGroupsManager();
    });

    refreshRepoList();

    return wrapper;
}

async function handleDeleteGroup(group) {
    if (!group || !group.name) {
        return;
    }
    const name = group.name || '';
    const ok = window.confirm(
        `Delete repo group "${name}"?\nThis does not delete the repositories themselves.`
    );
    if (!ok) {
        return;
    }
    try {
        await fetchJSON(`/api/repo-groups/${encodeURIComponent(group.name)}`, {
            method: 'DELETE',
        });
        if (groupUiState.editingId === group.name) {
            groupUiState.editingId = null;
        }
        if (typeof loadRepoGroups === 'function') {
            await loadRepoGroups();
        }
        renderRepoGroupsManager();
    } catch (err) {
        window.alert(`Delete failed: ${err.message}`);
    }
}

function renderRepoGroupsManager() {
    const list = document.querySelector('#group-list');
    const empty = document.querySelector('#group-empty');
    if (!list || !empty) {
        return;
    }

    list.innerHTML = '';
    const current = getState();
    const groups = Array.isArray(current.repoGroups) ? current.repoGroups : [];

    if (groupUiState.creating) {
        list.appendChild(buildGroupEditor('create', null));
    }

    groups.forEach((group) => {
        if (groupUiState.editingId === group.name) {
            list.appendChild(buildGroupEditor('edit', group));
        } else {
            list.appendChild(buildGroupRow(group));
        }
    });

    empty.style.display = groups.length || groupUiState.creating ? 'none' : 'block';
}

function bindGroupActions() {
    const createBtn = document.querySelector('#group-create');
    if (!createBtn) {
        return;
    }
    createBtn.addEventListener('click', () => {
        groupUiState.creating = true;
        groupUiState.editingId = null;
        renderRepoGroupsManager();
    });
}

window.renderRepoGroupsManager = renderRepoGroupsManager;

document.addEventListener('DOMContentLoaded', () => {
    bindGroupActions();
    renderRepoGroupsManager();
});
