// 全局变量
let currentView = 'grid'; // 'grid' 或 'table'
let allAlerts = [];
let filteredAlerts = [];
let cameras = new Set();
let defects = new Set();
let currentAlertDetails = null;

let currentSearchMode = 'cache'; // 'cache' 或 'file'
let fileSearchTimer = null;
let lastSearchParams = null;
let modeStartTime = null; // 记录模式切换时间
let isInitialLoad = true; // 标记是否为初始加载

let allCameras = new Set();  // 存储所有风机的集合
let cachedCameras = [];      // 缓存的排序后风机列表

let reportGenerationInProgress = false;
let downloadData = false;
let downloadImages = false;

// 风机号搜索功能
let cameraSearchActive = false;

// 全屏查看器相关变量
let zoomLevel = 1;
let isDragging = false;
let startX, startY;
let translateX = 0, translateY = 0;
let startTranslateX = 0, startTranslateY = 0;
let minZoom = 0.1;
let maxZoom = 5;
let zoomStep = 0.1;

// 分页器
let currentPage = 1;
let pageSize = 9; // 默认9条
let totalPages = 1;
let totalAlerts = 0;

// 缺陷名称映射（与后端同步）
const defectChineseMap = {
    'youwu': '油污',
    'gubao': '鼓包',
    'leiji': '雷击',
    'hangbiaoqi': '航标漆',
    'liewen': '裂纹',
    'kailie': '开裂',
    'tuoluo': '脱落',
    'fushi': '腐蚀',
    'mosunhuai': '膜损坏',
    'aoxian': '凹陷',
    'juchi': '锯齿',
    'raoliutiao': '扰流条',
    'fubing':'覆冰'
};

// 翻译缺陷名称
function translateDefectName(englishName) {
    return defectChineseMap[englishName] || englishName;
}

// 切换搜索模式
$('#toggleCameraSearchBtn').click(function() {
    cameraSearchActive = !cameraSearchActive;

    if (cameraSearchActive) {
        $('#cameraSearchContainer').show();
        $('#cameraFilter').hide();
        $('#cameraSearchInput').focus();
        $(this).html('<i class="bi bi-list"></i> 列表');
    } else {
        $('#cameraSearchContainer').hide();
        $('#cameraFilter').show();
        $(this).html('<i class="bi bi-search"></i> 搜索');
    }
});

// 风机号搜索输入事件
$('#cameraSearchInput').on('input', function() {
    const searchTerm = $(this).val().toLowerCase().trim();
    const select = $('#cameraFilter');
    const options = select.find('option');

    if (!searchTerm) {
        // 显示所有选项
        options.show();
    } else {
        // 筛选选项
        options.each(function() {
            const text = $(this).text().toLowerCase();
            $(this).toggle(text.includes(searchTerm));
        });
    }
});

// 关闭搜索
$('#cameraSearchToggle').click(function() {
    cameraSearchActive = false;
    $('#cameraSearchContainer').hide();
    $('#cameraFilter').show();
    $('#toggleCameraSearchBtn').html('<i class="bi bi-search"></i> 搜索');
    $('#cameraSearchInput').val('');
});

// 初始化时间过滤器
function initTimeFilters() {
    // 清空时间筛选器，避免自动触发文件搜索
    $('#startTime').val('');
    $('#endTime').val('');
}

// 初始化缺陷下拉框
function initDefectFilter() {
    const select = $('#defectFilter');
    const currentValue = select.val();

    select.empty();
    select.append('<option value="">全部缺陷</option>');

    // 按中文名排序后添加
    const sortedDefects = Object.entries(defectChineseMap)
        .map(([english, chinese]) => ({ english, chinese }))
        .sort((a, b) => a.chinese.localeCompare(b.chinese));

    sortedDefects.forEach(defect => {
        select.append(`<option value="${defect.english}">${defect.chinese}</option>`);
    });

    // 恢复之前选中的值
    if (currentValue && defectChineseMap[currentValue]) {
        select.val(currentValue);
    }

    console.log(`缺陷下拉框已初始化，共 ${sortedDefects.length} 个缺陷类型`);
}


// 格式化时间为datetime-local需要的格式
function formatDateTimeLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

// 更新时间显示
function updateTimeDisplay() {
    const now = new Date();
    const timeString = now.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });

    document.getElementById('currentTime').textContent = timeString;

    // 每秒更新
    setTimeout(updateTimeDisplay, 1000);
}

// 加载告警数据
function loadAlerts() {
    if (currentSearchMode === 'file' && lastSearchParams) {
        // 历史搜索模式，使用文件搜索API
        loadAlertsFromFile();
    } else {
        // 实时模式，使用缓存API
        loadAlertsFromCache();
    }
}


// 从缓存加载告警
function loadAlertsFromCache() {
    $.ajax({
        url: '/api/alerts',
        method: 'GET',
        dataType: 'json',
        data: {
            page: currentPage,
            per_page: pageSize
        },
        success: function(data) {
            handleAlertsResponse(data);

            // 验证缺陷下拉框
            validateDefectFilter();
        },
        error: function(xhr, status, error) {
            console.error('加载缓存告警失败:', error);
            $('#connectionStatus').removeClass('bg-success').addClass('bg-danger').text('连接失败');
        }
    });
}

// 验证缺陷下拉框
function validateDefectFilter() {
    const select = $('#defectFilter');
    const optionCount = select.find('option').length;
    const expectedCount = Object.keys(defectChineseMap).length + 1; // 加上"全部缺陷"

    console.log(`验证缺陷下拉框: 当前 ${optionCount} 个选项，预期 ${expectedCount} 个`);

    if (optionCount < expectedCount) {
        console.warn("缺陷下拉框选项不足，正在修复...");
        initializeFixedDefectFilter();
    }
}

// 从文件加载告警
function loadAlertsFromFile() {
    const startTime = $('#startTime').val();
    const endTime = $('#endTime').val();
    const cameraFilter = $('#cameraFilter').val();
    const defectFilter = $('#defectFilter').val();
    const confidenceMin = parseFloat($('#confidenceMin').val()) || 0;

    // 检查必要的搜索条件
    if (!startTime || !endTime) {
        alert('历史搜索需要设置开始时间和结束时间');
        switchToRealtimeMode();
        return;
    }

    // 保存搜索参数
    lastSearchParams = {
        start_time: startTime,
        end_time: endTime,
        camera_id: cameraFilter,
        defect_name: defectFilter,
        min_confidence: confidenceMin
    };

    $.ajax({
        url: '/api/alerts/search',
        method: 'GET',
        dataType: 'json',
        data: {
            page: currentPage,
            per_page: pageSize,
            start_time: startTime,
            end_time: endTime,
            camera_id: cameraFilter,
            defect_name: defectFilter,
            min_confidence: confidenceMin
        },
        success: function(data) {
            handleAlertsResponse(data);
        },
        error: function(xhr, status, error) {
            console.error('文件搜索失败:', error);
            alert('历史搜索失败：' + error);
            switchToRealtimeMode();
        }
    });
}

// 统一的响应处理
function handleAlertsResponse(data) {
    if (data.status === 'success' && data.alerts) {
        allAlerts = data.alerts;
        totalAlerts = data.pagination.total;
        totalPages = data.pagination.total_pages;

        // 如果是初次加载，标记为非初次
        if (isInitialLoad) {
            isInitialLoad = false;
        }

        // 提取筛选条件
        extractFilters();

        // 应用筛选（如果是实时模式，会进行前端筛选）
        applyLocalFilters();

        // 更新时间显示
        updateLastUpdateTime();

        // 更新分页器
        updatePagination();

        $('#connectionStatus').removeClass('bg-danger').addClass('bg-success').text('已连接');
    } else {
        console.error('加载告警数据失败:', data.message);
        $('#resultCount').text('加载失败');
    }
}


// 本地筛选（仅用于实时模式）
function applyLocalFilters() {
    if (currentSearchMode === 'cache') {
        const cameraFilter = $('#cameraFilter').val();
        const defectFilter = $('#defectFilter').val();
        const confidenceMin = parseFloat($('#confidenceMin').val()) || 0;
        const startTime = $('#startTime').val();
        const endTime = $('#endTime').val();

        filteredAlerts = allAlerts.filter(alert => {
            // 风机筛选
            if (cameraFilter && alert.camera_id !== cameraFilter) {
                return false;
            }

            // 缺陷筛选
            if (defectFilter) {
                const hasDefect = alert.detections.some(det => det.name === defectFilter);
                if (!hasDefect) {
                    return false;
                }
            }

            // 置信度筛选
            if (confidenceMin > 0) {
                const maxConfidence = Math.max(...alert.detections.map(det => det.conf));
                if (maxConfidence < confidenceMin) {
                    return false;
                }
            }

            // 时间筛选
            if (startTime) {
                const alertTime = new Date(alert.detection_time);
                const start = new Date(startTime);
                if (alertTime < start) {
                    return false;
                }
            }

            if (endTime) {
                const alertTime = new Date(alert.detection_time);
                const end = new Date(endTime);
                if (alertTime > end) {
                    return false;
                }
            }

            return true;
        });

        // 按时间倒序排序
        filteredAlerts.sort((a, b) => {
            return new Date(b.detection_time) - new Date(a.detection_time);
        });

        updateDisplay();
        updateResultCount();
    } else {
        // 历史搜索模式，直接使用API返回的数据
        filteredAlerts = allAlerts;
        updateDisplay();
        updateResultCount();
    }
}

// 分页更新
function updatePagination() {
    const paginationList = $('#paginationList');

    // 清除所有页码（保留上一页和下一页按钮）
    paginationList.find('.page-number').remove();
    paginationList.find('.page-ellipsis').remove();

    // 如果总页数小于等于1，隐藏分页器
    if (totalPages <= 1) {
        $('#paginationContainer').hide();
        updatePaginationInfo();
        return;
    }

    $('#paginationContainer').show();

    // 更新上一页按钮状态
    const prevBtn = $('#prevPageBtn');
    prevBtn.toggleClass('disabled', currentPage === 1);

    // 更新下一页按钮状态
    const nextBtn = $('#nextPageBtn');
    nextBtn.toggleClass('disabled', currentPage === totalPages);

    // 生成页码按钮
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    // 调整起始页，确保显示足够数量的页码
    if (endPage - startPage + 1 < maxVisiblePages) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    // 添加第一页按钮
    if (startPage > 1) {
        addPageButton(1, prevBtn);

//        // 添加省略号
//        if (startPage > 2) {
//            addEllipsis(prevBtn.next());
//        }
    }

    // 添加页码按钮
    for (let i = startPage; i <= endPage; i++) {
        const isActive = i === currentPage;
        addPageButton(i, null, isActive);
    }

    // 添加最后一页按钮
    if (endPage < totalPages) {
        // 添加省略号
//        if (endPage < totalPages - 1) {
//            addEllipsis($('.page-number').last());
//        }

        addPageButton(totalPages);
    }

    // 重新绑定事件
    bindPaginationEvents();
    updatePaginationInfo();
}

// 添加省略号
function addEllipsis(insertAfter) {
    const ellipsis = $('<li class="page-item disabled page-ellipsis"><span class="page-link">...</span></li>');
    insertAfter.after(ellipsis);
}

// 绑定分页事件
function bindPaginationEvents() {
    // 页码点击事件
    $(document).off('click', '.page-link[data-page]').on('click', '.page-link[data-page]', function(e) {
        e.preventDefault();
        currentPage = parseInt($(this).data('page'));
        loadAlerts();
    });

    // 上一页点击事件
    $('#prevPageBtn a').off('click').on('click', function(e) {
        e.preventDefault();
        if (currentPage > 1) {
            currentPage--;
            loadAlerts();
        }
    });

    // 下一页点击事件
    $('#nextPageBtn a').off('click').on('click', function(e) {
        e.preventDefault();
        if (currentPage < totalPages) {
            currentPage++;
            loadAlerts();
        }
    });
}

// 添加页码按钮
function addPageButton(pageNum, insertAfter = null, isActive = false) {
    const activeClass = isActive ? 'active' : '';
    const pageItem = $(`
        <li class="page-item page-number ${activeClass}">
            <a class="page-link" href="#" data-page="${pageNum}">${pageNum}</a>
        </li>
    `);

    if (insertAfter) {
        insertAfter.after(pageItem);
    } else {
        // 插入到上一页按钮之后，但要在其他页码按钮之前
        const lastPageNumber = $('.page-number').last();
        if (lastPageNumber.length) {
            lastPageNumber.after(pageItem);
        } else {
            $('#prevPageBtn').after(pageItem);
        }
    }
}


// 更新分页信息
function updatePaginationInfo() {
    const start = (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, totalAlerts);
    const displayText = totalAlerts === 0
        ? '暂无告警数据'
        : `正在显示第 ${start}-${end} 条告警，共 ${totalAlerts} 条`;
    $('#resultCount').text(displayText);
}

// 提取筛选条件
// 修改 extractFilters 函数，避免它覆盖缺陷下拉框
function extractFilters() {
    // 注意：这里不再更新缺陷下拉框，只更新风机下拉框
    cameras.clear();

    allAlerts.forEach(alert => {
        cameras.add(alert.camera_id);
    });

    // 只更新风机下拉框
    updateCameraFilter();

    // 不再调用 updateDefectFilter()，因为缺陷下拉框是固定的
    // 只收集当前页的缺陷用于高亮
    collectCurrentPageDefects();
}

// 收集当前页缺陷用于高亮
function collectCurrentPageDefects() {
    const currentPageDefects = new Set();

    allAlerts.forEach(alert => {
        alert.detections.forEach(det => {
            if (det.name) {
                currentPageDefects.add(det.name);
            }
        });
    });

    // 高亮当前页出现的缺陷
    highlightCurrentPageDefects(currentPageDefects);

    console.log(`当前页出现的缺陷: ${Array.from(currentPageDefects)}`);
}


// 更新风机号下拉框
function updateCameraFilter() {
    const select = $('#cameraFilter');
    const currentValue = select.val();
    select.empty();
    select.append('<option value="">全部风机</option>');

    Array.from(cameras).sort().forEach(camera => {
        select.append(`<option value="${camera}">${camera}</option>`);
    });

    if (currentValue && Array.from(cameras).includes(currentValue)) {
        select.val(currentValue);
    }
}

// 更新缺陷下拉框
function updateDefectFilter() {
    // 这个函数现在只用于高亮，不修改选项
    console.log("updateDefectFilter 被调用，但不会修改缺陷下拉框选项");

    // 只做高亮，不清空或添加选项
    collectCurrentPageDefects();
}

// 应用筛选条件
function applyFilters() {
    if (currentSearchMode === 'file') {
        // 历史搜索模式，重新从文件加载
        currentPage = 1; // 重置到第一页
        loadAlertsFromFile();
    } else {
        // 实时模式，在本地进行筛选
        currentPage = 1; // 重置到第一页
        applyLocalFilters();
    }
}


// 更新显示
function updateDisplay() {
    if (filteredAlerts.length === 0) {
        $('#gridView').hide();
        $('#tableView').hide();
        $('#emptyState').show();
        return;
    }

    $('#emptyState').hide();

    if (currentView === 'grid') {
        displayGridView();
    } else {
        displayTableView();
    }
}

// 显示宫格视图
function displayGridView() {
    const container = $('#gridView');
    container.empty();

    filteredAlerts.forEach(alert => {
        const card = createGridCard(alert);
        container.append(card);
    });

    $('#gridView').show();
    $('#tableView').hide();
}

// 创建宫格卡片
function createGridCard(alert) {
    const detectionTime = formatDateTime(alert.detection_time);
    const defectNames = alert.detections.map(det => translateDefectName(det.name)).join('、');
    const imageUrl = getAlertImageUrl(alert);
    return `
        <div class="grid-card" onclick="showAlertDetail('${alert.alert_id}')">
            <img src="${imageUrl}"
                 class="grid-image"
                 alt="${alert.camera_name}"
                 onerror="this.onerror=null; this.src='data:image/png;base64,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';">
            <div class="grid-content">
                <div class="grid-info">
                    <div class="grid-info-item">
                        <span class="grid-info-icon"><i class="bi bi-clock"></i></span>
                        <span class="grid-info-text">${detectionTime}</span>
                    </div>
                    <div class="grid-info-item">
                        <span class="grid-info-icon"><i class="bi bi-camera-video"></i></span>
                        <span class="grid-info-text">${alert.camera_name}</span>
                    </div>
                </div>
                <div class="defect-tag">${defectNames}</div>
            </div>
        </div>
    `;
}

// 格式化时间显示
function formatDateTime(dateTimeString) {
    const date = new Date(dateTimeString);
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
}

// 显示表格视图
function displayTableView() {
    const tbody = $('#tableBody');
    tbody.empty();

    filteredAlerts.forEach(alert => {
        const row = createTableRow(alert);
        tbody.append(row);
    });

    $('#gridView').hide();
    $('#tableView').show();
}

// 创建表格行
function createTableRow(alert) {
    const detectionTime = formatDateTime(alert.detection_time);
    const defectsHtml = alert.detections.map(det => {
        const chineseName = translateDefectName(det.name);
        return `<span class="defect-item">${chineseName} (${(det.conf * 100).toFixed(1)}%)</span>`;
    }).join('');

    return `
        <tr>
            <td>
                <img src="/alerts/images/${alert.image_filename || alert.alert_id + '.jpg'}"
                     class="table-image"
                     onclick="showAlertDetail('${alert.alert_id}')"
                     alt="预览"
                     onerror="this.onerror=null; this.src=
                     'data:image/png;base64,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'
                     ">
            </td>
            <td>
                <strong>${alert.camera_id}</strong><br>
                <small class="text-muted">${alert.camera_name}</small>
            </td>
            <td>${detectionTime}</td>
            <td>
                <span class="badge bg-primary">${alert.detection_count} 个</span>
            </td>
            <td class="defect-cell">${defectsHtml}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="showAlertDetail('${alert.alert_id}')">
                    <i class="bi bi-eye"></i> 详情
                </button>
            </td>
        </tr>
    `;
}

// 全屏图片查看器功能
function initFullscreenViewer() {
    const viewer = document.getElementById('fullscreenViewer');
    const image = document.getElementById('fullscreenImage');

    if (!viewer || !image) return;

    // 鼠标滚轮缩放
    viewer.addEventListener('wheel', function(e) {
        e.preventDefault();

        // 获取缩放方向
        const delta = e.deltaY > 0 ? -zoomStep : zoomStep;
        const newZoom = Math.max(minZoom, Math.min(maxZoom, zoomLevel + delta));

        if (newZoom !== zoomLevel) {
            zoomLevel = newZoom;
            applyFullscreenZoom();
        }
    }, { passive: false });

    // 鼠标拖拽
    image.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return; // 只处理左键

        isDragging = true;
        image.classList.add('grabbing');
        startX = e.clientX;
        startY = e.clientY;
        startTranslateX = translateX;
        startTranslateY = translateY;

        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;

        e.preventDefault();
        const deltaX = e.clientX - startX;
        const deltaY = e.clientY - startY;

        translateX = startTranslateX + deltaX;
        translateY = startTranslateY + deltaY;

        applyFullscreenTransform();
    });

    document.addEventListener('mouseup', function() {
        isDragging = false;
        image.classList.remove('grabbing');
    });

    // ESC键关闭查看器
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && viewer.classList.contains('active')) {
            closeFullscreenViewer();
        }
    });

    // 点击背景关闭查看器
    viewer.addEventListener('click', function(e) {
        if (e.target === viewer) {
            closeFullscreenViewer();
        }
    });

    // 触摸屏支持
    let touchStartX, touchStartY, touchStartDistance;

    image.addEventListener('touchstart', function(e) {
        if (e.touches.length === 1) {
            // 单指拖拽
            const touch = e.touches[0];
            touchStartX = touch.clientX;
            touchStartY = touch.clientY;
            startTranslateX = translateX;
            startTranslateY = translateY;
        } else if (e.touches.length === 2) {
            // 双指缩放
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            touchStartDistance = Math.sqrt(
                Math.pow(touch2.clientX - touch1.clientX, 2) +
                Math.pow(touch2.clientY - touch1.clientY, 2)
            );
        }

        e.preventDefault();
    }, { passive: false });

    image.addEventListener('touchmove', function(e) {
        if (e.touches.length === 1 && touchStartX !== undefined) {
            // 单指拖拽
            const touch = e.touches[0];
            const deltaX = touch.clientX - touchStartX;
            const deltaY = touch.clientY - touchStartY;

            translateX = startTranslateX + deltaX;
            translateY = startTranslateY + deltaY;

            applyFullscreenTransform();
            e.preventDefault();
        } else if (e.touches.length === 2 && touchStartDistance !== undefined) {
            // 双指缩放
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            const currentDistance = Math.sqrt(
                Math.pow(touch2.clientX - touch1.clientX, 2) +
                Math.pow(touch2.clientY - touch1.clientY, 2)
            );

            const delta = (currentDistance - touchStartDistance) * 0.01;
            const newZoom = Math.max(minZoom, Math.min(maxZoom, zoomLevel + delta));

            if (newZoom !== zoomLevel) {
                zoomLevel = newZoom;
                applyFullscreenZoom();
            }

            touchStartDistance = currentDistance;
            e.preventDefault();
        }
    }, { passive: false });

    image.addEventListener('touchend', function() {
        touchStartX = undefined;
        touchStartY = undefined;
        touchStartDistance = undefined;
    });
}

// 应用全屏查看器的缩放和位移
function applyFullscreenTransform() {
    const image = document.getElementById('fullscreenImage');
    if (!image) return;

    image.style.transform = `translate(${translateX}px, ${translateY}px) scale(${zoomLevel})`;
    document.getElementById('zoomIndicator').textContent = `${Math.round(zoomLevel * 100)}%`;
}

// 应用全屏查看器的缩放
function applyFullscreenZoom() {
    applyFullscreenTransform();
}

// 放大
function zoomIn() {
    zoomLevel = Math.min(maxZoom, zoomLevel + zoomStep);
    applyFullscreenZoom();
}

// 缩小
function zoomOut() {
    zoomLevel = Math.max(minZoom, zoomLevel - zoomStep);
    applyFullscreenZoom();
}

// 重置缩放和位置
function resetZoom() {
    zoomLevel = 1;
    translateX = 0;
    translateY = 0;
    applyFullscreenZoom();
}

// 打开全屏查看器
function openFullscreenViewer(imageSrc) {
    const viewer = document.getElementById('fullscreenViewer');
    const image = document.getElementById('fullscreenImage');

    if (!viewer || !image) return;

    // 设置图片源
    image.src = imageSrc;

    // 重置状态
    resetZoom();

    // 显示查看器
    viewer.classList.add('active');

    // 初始化查看器
    initFullscreenViewer();

    // 阻止背景滚动
    document.body.style.overflow = 'hidden';
}

// 关闭全屏查看器
function closeFullscreenViewer() {
    const viewer = document.getElementById('fullscreenViewer');
    if (!viewer) return;

    viewer.classList.remove('active');

    // 恢复背景滚动
    document.body.style.overflow = '';
}

// 显示告警详情
function showAlertDetail(alertId) {
    const alert = filteredAlerts.find(a => a.alert_id === alertId) ||
                 allAlerts.find(a => a.alert_id === alertId);

    if (!alert) return;

    currentAlertDetails = alert;

    // 更新基本信息
    $('#detailAlertId').text(alert.alert_id);
    $('#detailCameraName').text(`${alert.camera_name} (${alert.camera_id})`);
    $('#detailDetectionTime').text(formatDetailedTime(alert.detection_time));
    $('#detailDefectCount').text(`${alert.detection_count} 个缺陷`);

    // 设置图片
    const imageUrl = `/alerts/images/${alert.image_filename || alert.alert_id + '.jpg'}`;
    $('#detailImage').attr('src', imageUrl);

    // 更新缺陷列表
    updateDefectList(alert.detections);

    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('detailModal'));
    modal.show();
}

// 格式化详细时间
function formatDetailedTime(dateTimeString) {
    const date = new Date(dateTimeString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

// 更新缺陷列表
function updateDefectList(detections) {
    const container = document.getElementById('defectList');
    if (!container) return;

    container.innerHTML = '';

    detections.forEach((det, index) => {
        const chineseName = translateDefectName(det.name);
        const confidencePercent = (det.conf * 100).toFixed(1);

        const defectCard = document.createElement('div');
        defectCard.className = 'defect-card';
        defectCard.innerHTML = `
            <div class="defect-header">
                <span class="defect-name">缺陷 ${index + 1}: ${chineseName}</span>
                <span class="defect-confidence">${confidencePercent}%</span>
            </div>
            <div class="defect-coordinates">
                <div class="coordinate-item">
                    <div>X坐标</div>
                    <div>${det.x.toFixed(1)}</div>
                </div>
                <div class="coordinate-item">
                    <div>Y坐标</div>
                    <div>${det.y.toFixed(1)}</div>
                </div>
                <div class="coordinate-item">
                    <div>宽度</div>
                    <div>${det.w.toFixed(1)}</div>
                </div>
                <div class="coordinate-item">
                    <div>高度</div>
                    <div>${det.h.toFixed(1)}</div>
                </div>
                <div class="coordinate-item">
                    <div>旋转角度</div>
                    <div>${det.r ? det.r.toFixed(1) + '°' : '0°'}</div>
                </div>
            </div>
        `;

        container.appendChild(defectCard);
    });
}


// 修改更新结果数量
function updateResultCount() {
    const start = (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, totalAlerts);
    $('#resultCount').text(`正在显示第 ${start}-${end} 条告警，共 ${totalAlerts} 条`);
}

// 更新最后更新时间
function updateLastUpdateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });

    $('#lastUpdateTime').text(timeString);
}

// 重置筛选条件
function resetFilters() {
    $('#cameraFilter').val('');
    $('#defectFilter').val('');
    $('#confidenceMin').val('');
    $('#startTime').val('');
    $('#endTime').val('');

    // 如果当前是历史搜索模式，切换回实时模式
    if (currentSearchMode === 'file') {
        switchToRealtimeMode();
    }

    // 重新加载数据
    currentPage = 1;
    loadAlerts();
}

// 导出告警数据
function downloadAlertData() {
    if (!currentAlertDetails) return;

    const dataStr = JSON.stringify(currentAlertDetails, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);

    const exportFileDefaultName = `alert_${currentAlertDetails.alert_id}.json`;

    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
}




// 更新搜索模式指示器
function updateSearchModeIndicator() {
    const indicator = $('#searchModeIndicator');
    const timer = $('#modeTimer');

    if (currentSearchMode === 'file') {
        indicator.html('<span class="badge bg-warning">历史搜索模式</span>');

        // 计算剩余时间
        if (modeStartTime && fileSearchTimer) {
            const elapsed = Date.now() - modeStartTime;
            const remaining = 5 * 60 * 1000 - elapsed; // 5分钟
            if (remaining > 0) {
                const minutes = Math.floor(remaining / 60000);
                const seconds = Math.floor((remaining % 60000) / 1000);
                timer.text(`${minutes}:${seconds.toString().padStart(2, '0')}后自动返回实时模式`);
            } else {
                timer.text('即将返回实时模式...');
            }
        }
    } else {
        indicator.html('<span class="badge bg-success">实时模式</span>');
        timer.text('显示最近1000条实时告警');
    }
}


// 切换到历史搜索模式
function switchToHistoryMode() {
    if (currentSearchMode === 'file') return; // 已经是历史搜索模式

    currentSearchMode = 'file';
    modeStartTime = Date.now();

    // 更新按钮状态
    $('#historyModeBtn').removeClass('btn-outline-secondary').addClass('btn-primary');
    $('#realtimeModeBtn').removeClass('btn-primary').addClass('btn-outline-secondary');

    // 清除已有的定时器
    if (fileSearchTimer) {
        clearTimeout(fileSearchTimer);
    }

    // 设置5分钟后自动返回实时模式
    fileSearchTimer = setTimeout(() => {
        console.log('5分钟超时，自动切换回实时模式');
        switchToRealtimeMode();
        loadAlerts(); // 重新加载实时数据
    }, 5 * 60 * 1000);

    updateSearchModeIndicator();
    console.log('已切换到历史搜索模式');
}

// 切换到实时模式
function switchToRealtimeMode() {
    if (currentSearchMode === 'cache') return; // 已经是实时模式

    currentSearchMode = 'cache';
    lastSearchParams = null;
    modeStartTime = null;

    // 更新按钮状态
    $('#realtimeModeBtn').removeClass('btn-outline-secondary').addClass('btn-primary');
    $('#historyModeBtn').removeClass('btn-primary').addClass('btn-outline-secondary');

    // 清除定时器
    if (fileSearchTimer) {
        clearTimeout(fileSearchTimer);
        fileSearchTimer = null;
    }

    // 重置时间筛选器（可选，可以保留用户设置的时间）
    // initTimeFilters();

    updateSearchModeIndicator();
    console.log('已切换到实时模式');
}



function getAlertImageUrl(alert) {
    // 如果有相对路径，使用分层结构
    if (alert.relative_path) {
        return `/alerts/images/${alert.relative_path}/images/${alert.alert_id}.jpg`;
    }
    // 否则使用旧格式
    return `/alerts/images/${alert.image_filename || alert.alert_id + '.jpg'}`;
}


function initCameraFilter() {
    const select = $('#cameraFilter');
    select.empty();
    select.append('<option value="">全部风机</option>');

    // 显示加载中状态
    select.append('<option value="" disabled>加载风机列表中...</option>');

    // 异步加载所有风机号
    loadAllCameras();
}

// 修改加载所有风机号的函数
function loadAllCameras() {
    $.ajax({
        url: '/api/cameras',
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            if (data.status === 'success' && data.cameras) {
                // 更新全局风机集合
                allCameras.clear();
                data.cameras.forEach(camera => {
                    allCameras.add(camera);
                });

                // 缓存排序后的列表
                cachedCameras = data.cameras;

                // 更新下拉框
                updateAllCamerasFilter();
                console.log(`已加载 ${data.cameras.length} 个风机号`);
            } else {
                // 如果API失败，使用默认列表
                useDefaultCameras();
            }
        },
        error: function(xhr, status, error) {
            console.error('加载风机列表失败:', error);
            // 失败时使用默认风机列表
            useDefaultCameras();
        }
    });
}

// 默认风机列表（当API不可用时）
function useDefaultCameras() {
    const defaultCameras = ['A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'A07', 'A08', 'A09', 'A10', 'A11', 'A12', 'B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B09', 'B10', 'B11', 'B12', 'B13', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C11', 'D01', 'D02', 'D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10', 'D11', 'D12', 'D13', 'D15'];

    allCameras.clear();
    defaultCameras.forEach(camera => {
        allCameras.add(camera);
    });

    cachedCameras = [...defaultCameras];
    updateAllCamerasFilter();
    console.log('使用默认风机列表');
}

// 更新显示所有风机的下拉框
function updateAllCamerasFilter() {
    const select = $('#cameraFilter');
    const currentValue = select.val();

    select.empty();
    select.append('<option value="">全部风机</option>');

    // 从管理器获取风机列表
    const cameras = cameraManager.getAll();

    if (cameras.length === 0) {
        select.append('<option value="" disabled>暂无风机数据</option>');
        return;
    }

    // 使用智能分组排序
    const sortedCameras = groupCamerasIntelligently(cameras);

    // 添加选项
    sortedCameras.forEach(camera => {
        select.append(`<option value="${camera}">${camera}</option>`);
    });

    // 恢复选中状态
    if (currentValue && cameras.includes(currentValue)) {
        select.val(currentValue);
    }
}

// 刷新按钮事件
$('#refreshCamerasBtn').click(function() {
    const icon = $(this).find('i');
    icon.addClass('spin');

    cameraManager.forceRefresh().then(() => {
        updateAllCamerasFilter();
        showNotification('风机列表已刷新', 'success');
    }).catch(() => {
        showNotification('风机列表刷新失败', 'error');
    }).finally(() => {
        setTimeout(() => {
            icon.removeClass('spin');
        }, 500);
    });
});

// 智能分组风机号
function groupCamerasIntelligently(cameras) {
    if (!cameras || cameras.length === 0) return cameras;

    // 尝试识别风机号模式并进行分组
    const patterns = {
        'A': /^A(\d+)$/i,
        'B': /^B(\d+)$/i,
        'C': /^C(\d+)$/i,
        'D': /^D(\d+)$/i,
    };

    // 找出最匹配的模式
    let matchedPattern = null;
    for (const [prefix, pattern] of Object.entries(patterns)) {
        if (cameras.some(camera => pattern.test(camera))) {
            matchedPattern = pattern;
            break;
        }
    }

    // 如果有匹配的模式，按数字排序
    if (matchedPattern) {
        return cameras.sort((a, b) => {
            const aMatch = a.match(matchedPattern);
            const bMatch = b.match(matchedPattern);

            if (aMatch && bMatch) {
                const aNum = parseInt(aMatch[1], 10);
                const bNum = parseInt(bMatch[1], 10);
                return aNum - bNum;
            }

            // 如果匹配失败，按字符串排序
            return a.localeCompare(b);
        });
    }

    // 否则按自然排序
    return cameras.sort((a, b) => a.localeCompare(b, undefined, {numeric: true}));
}


// 风机号缓存管理
class CameraManager {
    constructor() {
        this.cameras = new Set();
        this.cachedList = [];
        this.lastUpdate = 0;
        this.cacheDuration = 5 * 60 * 1000; // 5分钟缓存
        this.isLoading = false;
    }

    // 加载所有风机号
    load() {
        // 如果正在加载或缓存未过期，跳过
        if (this.isLoading) {
            console.log('风机列表正在加载中...');
            return Promise.resolve(this.cachedList);
        }

        const now = Date.now();
        if (now - this.lastUpdate < this.cacheDuration && this.cachedList.length > 0) {
            console.log('使用缓存的风机列表');
            return Promise.resolve(this.cachedList);
        }

        this.isLoading = true;

        return new Promise((resolve, reject) => {
            $.ajax({
                url: '/api/cameras',
                method: 'GET',
                dataType: 'json',
                success: (data) => {
                    this.isLoading = false;
                    this.lastUpdate = Date.now();

                    if (data.status === 'success' && data.cameras) {
                        // 更新缓存
                        this.cameras.clear();
                        data.cameras.forEach(camera => this.cameras.add(camera));
                        this.cachedList = data.cameras;

                        console.log(`风机列表更新成功，共 ${data.cameras.length} 个风机`);
                        resolve(this.cachedList);
                    } else {
                        console.error('风机列表API返回错误:', data.message);
                        reject(new Error('风机列表加载失败'));
                    }
                },
                error: (xhr, status, error) => {
                    this.isLoading = false;
                    console.error('风机列表加载失败:', error);
                    reject(error);
                }
            });
        });
    }

    // 获取所有风机号
    getAll() {
        return [...this.cachedList];
    }

    // 添加单个风机号
    add(cameraId) {
        if (cameraId && !this.cameras.has(cameraId)) {
            this.cameras.add(cameraId);
            this.cachedList = Array.from(this.cameras).sort();
            this.lastUpdate = Date.now(); // 重置缓存时间
            return true;
        }
        return false;
    }

    // 强制刷新
    forceRefresh() {
        this.lastUpdate = 0;
        return this.load();
    }

    // 检查是否存在
    has(cameraId) {
        return this.cameras.has(cameraId);
    }
}

// 初始化全局风机管理器
const cameraManager = new CameraManager();


// 只提取当前页面的缺陷类型（用于高亮显示）
function extractFiltersForCurrentPage() {
    // 清空当前页缺陷集合
    currentPageDefects.clear();

    // 收集当前页出现的缺陷
    allAlerts.forEach(alert => {
        alert.detections.forEach(det => {
            if (det.name) {
                currentPageDefects.add(det.name);
            }
        });
    });

    // 可选：高亮显示当前页出现的缺陷
    highlightCurrentPageDefects();
}

// 高亮显示当前页出现的缺陷
function highlightCurrentPageDefects(currentDefects) {
    const select = $('#defectFilter');
    const options = select.find('option');

    options.each(function() {
        const $option = $(this);
        const optionValue = $option.val();

        if (optionValue && currentDefects.has(optionValue)) {
            $option.addClass('text-primary fw-bold');
        } else {
            $option.removeClass('text-primary fw-bold');
        }
    });
}

// 按类别分组显示缺陷
function initDefectFilterGrouped() {
    const select = $('#defectFilter');
    const currentValue = select.val();

    // 清空下拉框
    select.empty();
    select.append('<option value="">全部缺陷</option>');

    // 定义缺陷分类（根据你的业务需求）
    const defectCategories = {
        '表面缺陷': ['youwu', 'hangbiaoqi', 'fushi', 'mosunhuai'],
        '结构缺陷': ['liewen', 'kailie', 'gubao', 'aoxian'],
        '外部损伤': ['leiji', 'juchi', 'raoliutiao'],
        '其他缺陷': ['tuoluo']
    };

    // 添加分类分组
    Object.entries(defectCategories).forEach(([category, defects]) => {
        // 过滤出存在的缺陷
        const validDefects = defects.filter(defect => defectChineseMap[defect]);

        if (validDefects.length > 0) {
            select.append(`<optgroup label="${category}">`);

            validDefects.forEach(defectKey => {
                const chineseName = defectChineseMap[defectKey];
                select.append(`<option value="${defectKey}">${chineseName}</option>`);
            });

            select.append('</optgroup>');
        }
    });

    // 恢复之前选中的值
    if (currentValue && defectChineseMap[currentValue]) {
        select.val(currentValue);
    }

    console.log('缺陷下拉框已按分类初始化');
}

function confirmGenerateReport() {
    // 可以直接调用generateReportFromPreview
    generateReportFromPreview();
}


// 固定缺陷下拉框初始化函数（独立，不会被覆盖）
function initializeFixedDefectFilter() {
    console.log("开始初始化固定缺陷下拉框...");

    const select = $('#defectFilter');
    if (!select.length) {
        console.error("错误：找不到缺陷下拉框元素");
        return;
    }

    // 保存当前选中的值
    const currentValue = select.val();

    // 清空下拉框
    select.empty();

    // 添加"全部缺陷"选项
    select.append('<option value="">全部缺陷</option>');

    // 将缺陷按中文名排序
    const sortedDefects = Object.entries(defectChineseMap)
        .map(([english, chinese]) => ({ english, chinese }))
        .sort((a, b) => a.chinese.localeCompare(b.chinese));

    // 添加所有缺陷选项
    sortedDefects.forEach(defect => {
        select.append(`<option value="${defect.english}">${defect.chinese}</option>`);
    });

    // 恢复之前选中的值
    if (currentValue && defectChineseMap[currentValue]) {
        select.val(currentValue);
    }

    console.log(`固定缺陷下拉框初始化完成，共添加 ${sortedDefects.length} 个缺陷`);
}


// 初始化报告生成功能
function initReportGeneration() {
    // 报告生成按钮点击事件
    $('#generateReportBtn').click(function(e) {
        e.stopPropagation();

        if (currentSearchMode !== 'file') {
            alert('请在历史搜索模式下生成报告');
            $(this).dropdown('hide');
            return;
        }

        // 检查是否已设置时间范围
        const startTime = $('#startTime').val();
        const endTime = $('#endTime').val();

        if (!startTime || !endTime) {
            alert('请先设置时间范围');
            $(this).dropdown('hide');
            return;
        }
    });

    // 确认生成报告按钮事件
    // 修改确认生成报告按钮事件中的提示文本
$('#confirmGenerateReportBtn').click(function() {
    if (reportGenerationInProgress) {
        return;
    }

    // 获取选项状态
    downloadData = $('#downloadDataCheck').is(':checked');
    downloadImages = $('#downloadImagesCheck').is(':checked');

    // 收集搜索条件
    const startTime = $('#startTime').val();
    const endTime = $('#endTime').val();
    const cameraFilter = $('#cameraFilter').val();
    const defectFilter = $('#defectFilter').val();
    const confidenceMin = parseFloat($('#confidenceMin').val()) || 0;

    if (!startTime || !endTime) {
        alert('请设置开始时间和结束时间');
        return;
    }

    // 确认生成报告 - 修改提示文本
    const optionText = [];
    if (downloadData) optionText.push('下载源数据Excel');
    if (downloadImages) optionText.push('下载缺陷图片文件包');  // 修改提示

    const confirmMessage = `确定生成Word报告吗？\n\n` +
                          `时间范围: ${startTime} 至 ${endTime}\n` +
                          `风机号: ${cameraFilter || '全部'}\n` +
                          `缺陷类型: ${defectFilter || '全部'}\n` +
                          `备注:\n` +
                          `  • Word报告中始终包含缺陷图片\n` +  // 新增说明
                          `  • 额外选项: ${optionText.length > 0 ? optionText.join('、') : '无'}`;

    if (!confirm(confirmMessage)) {
        return;
    }

    // 关闭下拉菜单
    $('#reportDropdown').dropdown('hide');

    // 生成报告
    generateWordReport({
        start_time: startTime,
        end_time: endTime,
        camera_id: cameraFilter || '',
        defect_name: defectFilter || '',
        min_confidence: confidenceMin,
        download_data: downloadData,
        download_images: downloadImages
    });
});
}



// 生成Word报告函数
function generateWordReport(reportData) {
    reportGenerationInProgress = true;

    // 保存原始按钮状态
    const originalBtn = $('#generateReportBtn');
    const originalIcon = originalBtn.find('i').clone();
    const originalText = originalBtn.html();

    // 更新按钮状态为生成中
    originalBtn.html('<i class="bi bi-hourglass-split spin"></i> 生成中...');
    originalBtn.prop('disabled', true);

    // 显示加载遮罩
    showLoadingOverlay('正在生成Word报告，请稍候...');

    // 发送生成报告请求
    $.ajax({
        url: '/api/report/generate-word',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(reportData),
        xhrFields: {
            responseType: 'blob'  // 接收二进制数据
        },
        success: function(data, status, xhr) {
            // 隐藏加载遮罩
            hideLoadingOverlay();

            // 从响应头获取文件名
            let filename = '风机检测报告.docx';
            const contentDisposition = xhr.getResponseHeader('Content-Disposition');
            if (contentDisposition) {
                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(contentDisposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }

            // 创建下载链接
            const blob = new Blob([data], {
                type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();

            // 清理
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            // 显示成功消息
            showNotification('Word报告生成成功！', 'success');
        },
        error: function(xhr, status, error) {
            hideLoadingOverlay();

            let errorMessage = '报告生成失败';
            try {
                const errorData = JSON.parse(xhr.responseText);
                errorMessage = errorData.message || errorMessage;
            } catch (e) {
                errorMessage = error || errorMessage;
            }

            showNotification(errorMessage, 'error');
            console.error('报告生成失败:', error);
        },
        complete: function() {
            // 恢复按钮状态
            reportGenerationInProgress = false;
            originalBtn.html(originalText);
            originalBtn.prop('disabled', false);
        }
    });
}

// 显示加载遮罩
function showLoadingOverlay(message = '正在处理，请稍候...') {
    // 移除已存在的遮罩
    $('#loadingOverlay').remove();

    // 创建遮罩
    const overlay = $(`
        <div id="loadingOverlay" style="
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.7);
            z-index: 9999;
            display: flex;
            justify-content: center;
            align-items: center;
            color: white;
            flex-direction: column;
        ">
            <div class="spinner-border" style="width:3rem;height:3rem;margin-bottom:1rem;" role="status">
                <span class="visually-hidden">下载中...</span>
            </div>
            <div style="font-size:1.2rem;">${message}</div>
        </div>
    `);

    $('body').append(overlay);
}

// 隐藏加载遮罩
function hideLoadingOverlay() {
    $('#loadingOverlay').remove();
}

// 显示通知
function showNotification(message, type = 'info') {
    // 移除已存在的通知
    $('.alert-notification').remove();

    const alertClass = type === 'success' ? 'alert-success' :
                      type === 'error' ? 'alert-danger' :
                      type === 'warning' ? 'alert-warning' : 'alert-info';

    const notification = $(`
        <div class="alert ${alertClass} alert-dismissible fade show alert-notification"
             style="position:fixed;top:20px;right:20px;z-index:9999;min-width:300px;">
            <div class="d-flex align-items-center">
                <i class="bi ${type === 'success' ? 'bi-check-circle' : type === 'error' ? 'bi-x-circle' : 'bi-info-circle'} me-2"></i>
                <div>${message}</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `);

    $('body').append(notification);

    // 3秒后自动消失
    setTimeout(() => {
        notification.alert('close');
    }, 3000);
}


// 初始化
$(document).ready(function() {


    initializeFixedDefectFilter();
    // 初始化时间过滤器
    initTimeFilters();

    // 更新时间显示
    updateTimeDisplay();

    // 设置初始模式为实时模式
    switchToRealtimeMode();

    // 立即加载风机列表
    loadAllCameras();

    // 加载初始数据
    loadAlerts();

    // 初始化风机管理器
    cameraManager.load().then(() => {
        updateAllCamerasFilter();
    }).catch(() => {
        // 加载失败时使用默认列表
        useDefaultCameras();
    });

    // 报告生成相关初始化
    initReportGeneration();


    // 模式切换按钮事件
    $('#realtimeModeBtn').click(function() {
        switchToRealtimeMode();
        currentPage = 1;
        loadAlerts();
    });

    $('#historyModeBtn').click(function() {
        switchToHistoryMode();
    });

    // 筛选按钮事件
    $('#loadBtn').click(function() {
        applyFilters();
    });

    // 刷新按钮事件
    $('#refreshBtn').click(function() {
        const icon = $(this).find('i');
        icon.addClass('spin');
        loadAlerts();
        setTimeout(() => {
            icon.removeClass('spin');
        }, 500);
    });

        // 视图切换按钮事件 - 修复绑定
    $('#gridViewBtn').off('click').on('click', function() {
        console.log('切换到宫格视图');
        currentView = 'grid';
        $(this).addClass('active');
        $('#tableViewBtn').removeClass('active');
        updateDisplay();
    });

    $('#tableViewBtn').off('click').on('click', function() {
        console.log('切换到表格视图');
        currentView = 'table';
        $(this).addClass('active');
        $('#gridViewBtn').removeClass('active');
        updateDisplay();
    });

    // 初始化视图状态
    $('#gridViewBtn').addClass('active');
    $('#tableViewBtn').removeClass('active');

    // 输入框回车事件
    $('#cameraFilter, #defectFilter, #confidenceMin, #startTime, #endTime').keypress(function(e) {
        if (e.which === 13) {
            applyFilters();
        }
    });

    // 每页显示数量选择器事件
    $('#pageSizeSelect').change(function() {
        pageSize = parseInt($(this).val());
        currentPage = 1;
        loadAlerts();
    });

    // 自动刷新（每30秒，仅实时模式）
    setInterval(function() {
        if (currentSearchMode === 'cache') {
            loadAlerts();
        }
        // 更新模式指示器的时间显示
        updateSearchModeIndicator();
    }, 30000);

    // 每秒更新倒计时显示
    setInterval(updateSearchModeIndicator, 1000);
});

