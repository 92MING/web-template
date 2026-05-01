import { BuiltinToast } from "/shared/components.js?v=20260429-2";
import { createPageBootstrap } from "/shared/page-bootstrap.js?v=20260429-2";

const copy = {
  "zh-cn": {
    sidebarEyebrow: "文字频道",
    sidebarTitle: "教室聊天室",
    sidebarCopy: "左边是教室频道和会议入口，右边保留作业、白板和共享文件，课堂本身直接嵌在当前页面里。",
    backStudent: "返回学生端",
    backTeacher: "返回老师端",
    search: "搜索",
    searchTitle: "搜索聊天记录",
    searchPlaceholder: "搜索消息、同学或关键词",
    searchEmpty: "没有匹配的聊天记录",
    send: "发送",
    attach: "附件",
    logout: "退出",
    roomMeta: "纯文字聊天室 + 课程日历 + 内嵌实时课堂",
    infoRoom: "房间",
    infoCalendar: "课程日历",
    infoTimeline: "近期安排",
    infoHomework: "作业与提交",
    infoMeetings: "会议列表",
    infoWhiteboard: "老师白板",
    infoMembers: "成员",
    infoFiles: "共享文件",
    fileFilterAll: "全部",
    fileFilterImage: "图片",
    fileFilterDoc: "文档",
    fileFilterMedia: "媒体",
    fileFilterOther: "其他",
    roomEmpty: "还没有任何教室",
    roomEmptyDesc: "先在老师端创建教室，再回来这里切换频道。",
    noMessages: "还没有消息，发一条开始聊天。",
    noFiles: "当前没有共享文件",
    noFilesInFilter: "这个分类下还没有共享文件",
    noMembers: "当前没有成员",
    unknownUser: "未知用户",
    textOnly: "文字聊天室",
    sendFailed: "发送失败",
    fileSelected: "已选择文件",
    today: "今天",
    yesterday: "昨天",
    jumpToMessage: "定位消息",
    fileShowing: "显示 {count}/{total}",
    teacherRole: "老师端",
    studentRole: "学生端",
    roomCount: "个频道",
    memberCount: "位成员",
    messageCount: "条消息",
    meetingDockTitle: "课堂会议",
    plannerOpen: "安排",
    calendar: "课程日历",
    liveClass: "立即开课",
    scheduleClass: "预约课堂",
    plannerTitle: "安排课堂",
    plannerType: "安排类型",
    plannerHomework: "作业",
    plannerMeeting: "线上课堂",
    plannerItemTitle: "标题",
    plannerDescription: "说明",
    plannerDue: "截止时间",
    plannerScheduled: "开课时间",
    plannerMode: "课堂模式",
    plannerScheduledMode: "预约课堂",
    plannerInstantMode: "立即开课",
    plannerHelp: "老师可以直接从这里把作业和线上课堂放进教室日历。",
    plannerSubmit: "发布",
    plannerCancel: "取消",
    submissionTitle: "提交作业",
    submissionSummaryEmpty: "选中作业后可在这里上传文件。",
    submissionNote: "提交说明",
    submissionFile: "上传文件",
    submissionSubmit: "提交",
    submissionCancel: "取消",
    submissionReviewTitle: "作业提交",
    submissionReviewAction: "查看提交",
    submissionReviewEmpty: "还没有学生提交这份作业。",
    submissionStudentLabel: "提交人",
    submissionSubmittedAt: "提交时间",
    submissionDownload: "下载附件",
    submissionGradeLabel: "评分",
    submissionFeedbackLabel: "反馈",
    submissionReviewSave: "保存批改",
    submissionReviewSaved: "批改已保存。",
    submissionNoGrade: "未批改",
    submissionNoFeedback: "暂无反馈",
    meetingStageTitle: "线上课堂",
    meetingCallTab: "课堂通话",
    meetingWhiteboardTab: "白板",
    broadcastWhiteboard: "广播白板",
    endMeeting: "结束课堂",
    minimizeMeeting: "缩到左侧",
    meetingNotReady: "这场课堂还没开始。",
    homeworkCreated: "作业已加入课程日历。",
    meetingCreated: "课堂安排已更新。",
    whiteboardSaved: "白板快照已广播到课堂。",
    submissionSuccess: "作业提交成功。",
    missingFile: "请先选择要上传的文件。",
    timelineEmpty: "暂无作业或会议安排。",
    meetingEmpty: "当前没有课堂安排。",
    meetingDockEmpty: "没有正在进行或预约的会议。",
    homeworkEmpty: "当前没有作业。",
    whiteboardEmpty: "老师还没有广播白板内容。",
    upcomingHomework: "最近作业",
    liveMeeting: "正在进行",
    nextMeeting: "下一场课堂",
    openMeeting: "进入课堂",
    startMeeting: "开始课堂",
    endMeetingAction: "结束",
    scheduleHint: "课堂内嵌在当前页面，关闭后会缩到左侧 dock。",
    submitHomework: "提交作业",
    updateSubmission: "更新提交",
    homeworkNotice: "新作业",
    meetingNotice: "课堂邀请",
    whiteboardTeacherHint: "老师可以在这里画板书，再点击“广播白板”同步给学生。",
    whiteboardStudentHint: "学生端显示老师最近一次广播的板书快照。",
    roleTeacher: "老师",
    roleStudent: "学生",
    statuses: {
      live: "进行中",
      scheduled: "已预约",
      ended: "已结束",
      pending: "待提交",
      submitted: "已提交",
      graded: "已批改",
      published: "已发布",
    },
  },
  en: {
    sidebarEyebrow: "Text Channels",
    sidebarTitle: "Classroom Chat",
    sidebarCopy: "The left side keeps channels and meeting entries, while the right side keeps deadlines, whiteboard snapshots, and shared files in the same room.",
    backStudent: "Back to Student",
    backTeacher: "Back to Teacher",
    search: "Search",
    searchTitle: "Search Chat",
    searchPlaceholder: "Search messages, classmates, or keywords",
    searchEmpty: "No matching messages",
    send: "Send",
    attach: "Attach",
    logout: "Sign out",
    roomMeta: "Text chat + calendar + embedded live classroom",
    infoRoom: "Room",
    infoCalendar: "Calendar",
    infoTimeline: "Upcoming",
    infoHomework: "Homework",
    infoMeetings: "Meetings",
    infoWhiteboard: "Teacher Whiteboard",
    infoMembers: "Members",
    infoFiles: "Shared Files",
    fileFilterAll: "All",
    fileFilterImage: "Images",
    fileFilterDoc: "Docs",
    fileFilterMedia: "Media",
    fileFilterOther: "Other",
    roomEmpty: "No classrooms yet",
    roomEmptyDesc: "Create a classroom first, then return here to switch channels.",
    noMessages: "No messages yet. Send one to start the thread.",
    noFiles: "No shared files yet",
    noFilesInFilter: "No shared files in this filter",
    noMembers: "No members yet",
    unknownUser: "Unknown user",
    textOnly: "Text Chat",
    sendFailed: "Failed to send",
    fileSelected: "File selected",
    today: "Today",
    yesterday: "Yesterday",
    jumpToMessage: "Jump to Message",
    fileShowing: "Showing {count}/{total}",
    teacherRole: "Teacher",
    studentRole: "Student",
    roomCount: "channels",
    memberCount: "members",
    messageCount: "messages",
    meetingDockTitle: "Class Meetings",
    plannerOpen: "Plan",
    calendar: "Calendar",
    liveClass: "Start Live Class",
    scheduleClass: "Schedule Class",
    plannerTitle: "Plan Classroom",
    plannerType: "Entry Type",
    plannerHomework: "Homework",
    plannerMeeting: "Live Classroom",
    plannerItemTitle: "Title",
    plannerDescription: "Description",
    plannerDue: "Due Time",
    plannerScheduled: "Start Time",
    plannerMode: "Class Mode",
    plannerScheduledMode: "Scheduled",
    plannerInstantMode: "Start Now",
    plannerHelp: "Teachers can create homework and live sessions directly from the classroom calendar.",
    plannerSubmit: "Publish",
    plannerCancel: "Cancel",
    submissionTitle: "Submit Homework",
    submissionSummaryEmpty: "Pick a homework item to upload a file.",
    submissionNote: "Submission Note",
    submissionFile: "Upload File",
    submissionSubmit: "Submit",
    submissionCancel: "Cancel",
    submissionReviewTitle: "Homework Submissions",
    submissionReviewAction: "View Submissions",
    submissionReviewEmpty: "No student submissions for this homework yet.",
    submissionStudentLabel: "Student",
    submissionSubmittedAt: "Submitted",
    submissionDownload: "Download File",
    submissionGradeLabel: "Grade",
    submissionFeedbackLabel: "Feedback",
    submissionReviewSave: "Save Review",
    submissionReviewSaved: "Review saved.",
    submissionNoGrade: "Not graded",
    submissionNoFeedback: "No feedback yet",
    meetingStageTitle: "Live Classroom",
    meetingCallTab: "Call",
    meetingWhiteboardTab: "Whiteboard",
    broadcastWhiteboard: "Broadcast Board",
    endMeeting: "End Class",
    minimizeMeeting: "Dock Left",
    meetingNotReady: "This classroom session has not started yet.",
    homeworkCreated: "Homework added to the classroom calendar.",
    meetingCreated: "Classroom schedule updated.",
    whiteboardSaved: "Whiteboard snapshot broadcasted.",
    submissionSuccess: "Homework submitted.",
    missingFile: "Select a file first.",
    timelineEmpty: "No homework or meetings yet.",
    meetingEmpty: "No classroom sessions yet.",
    meetingDockEmpty: "No live or scheduled meetings.",
    homeworkEmpty: "No homework yet.",
    whiteboardEmpty: "The teacher has not broadcasted a whiteboard snapshot yet.",
    upcomingHomework: "Upcoming Homework",
    liveMeeting: "Live Now",
    nextMeeting: "Next Class",
    openMeeting: "Open Class",
    startMeeting: "Start Session",
    endMeetingAction: "End",
    scheduleHint: "The class stays embedded here and can be minimized into the left dock.",
    submitHomework: "Submit",
    updateSubmission: "Update Submission",
    homeworkNotice: "New Homework",
    meetingNotice: "Class Invite",
    whiteboardTeacherHint: "Teachers can draw here and click broadcast to update the classroom snapshot.",
    whiteboardStudentHint: "Students see the latest whiteboard snapshot here.",
    roleTeacher: "Teacher",
    roleStudent: "Student",
    statuses: {
      live: "Live",
      scheduled: "Scheduled",
      ended: "Ended",
      pending: "Pending",
      submitted: "Submitted",
      graded: "Graded",
      published: "Published",
    },
  },
};

let currentLang = localStorage.getItem("eclass_lang") || "zh-cn";
let currentRole = localStorage.getItem("eclass_role") || "student";
let currentUserId = localStorage.getItem("eclass_user") || "";
let currentUserName = "";
let currentClassId = new URLSearchParams(location.search).get("class_id") || "c1";
let allClassrooms = [];
let roomStats = new Map();
let currentMessages = [];
let currentMembers = [];
let selectedFile = null;
let currentFileFilter = "all";
let pollHandle = null;
let workspaceData = {
  classroom: null,
  can_manage: false,
  homework: [],
  meetings: [],
  calendar: [],
};
let activeMeetingId = "";
let meetingStageTab = "call";
let meetingMinimized = false;
let pendingSubmissionHomeworkId = "";
let shouldBroadcastWhiteboard = false;
let activeReviewHomeworkId = "";

const shell = createPageBootstrap({
  pageTitleKey: "eclass.chatroom",
  translationPath: "/translate.json?v=20260429-2",
  validateRole: (role) => role === "teacher" || role === "student",
  getInvalidRoleRedirect: () => "login.html",
  onApplyI18n: async ({ lang }) => {
    currentLang = lang;
    applyCopy();
    renderRoomList();
    renderWorkspace();
    renderMessages(currentMessages);
    renderMembers(currentMembers);
    renderSharedFiles(currentMessages);
  },
  onReady: async ({ session }) => {
    const user = session.user || {};
    currentRole = user.role || localStorage.getItem("eclass_role") || currentRole;
    currentUserId = String(user.user_id || user.id || localStorage.getItem("eclass_user") || currentUserId);
    currentUserName = String(user.name || user.nickname || currentUserId || "Guest");
  },
});

const { $, api } = shell;

function d() {
  return copy[currentLang] || copy["zh-cn"];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;");
}

function normalizeTimestamp(value) {
  if (!value) return Number.NaN;
  if (typeof value === "number") {
    return value > 1_000_000_000_000 ? value : value * 1000;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.NaN : parsed;
}

function formatStamp(value) {
  const raw = normalizeTimestamp(value);
  if (Number.isNaN(raw)) return "";
  return new Intl.DateTimeFormat(currentLang === "en" ? "en-US" : "zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(raw));
}

function formatShortDate(value) {
  const raw = normalizeTimestamp(value);
  if (Number.isNaN(raw)) return "";
  return new Intl.DateTimeFormat(currentLang === "en" ? "en-US" : "zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(raw));
}

function dayKey(value) {
  const raw = normalizeTimestamp(value);
  if (Number.isNaN(raw)) return "unknown";
  const date = new Date(raw);
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()].join("-");
}

function formatDayLabel(value) {
  const raw = normalizeTimestamp(value);
  if (Number.isNaN(raw)) return "";
  const target = new Date(raw);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const targetKey = dayKey(raw);
  if (targetKey === dayKey(today.getTime())) return d().today;
  if (targetKey === dayKey(yesterday.getTime())) return d().yesterday;
  return new Intl.DateTimeFormat(currentLang === "en" ? "en-US" : "zh-CN", {
    month: "short",
    day: "numeric",
  }).format(target);
}

function toDatetimeLocal(value) {
  const raw = normalizeTimestamp(value);
  const date = Number.isNaN(raw) ? new Date() : new Date(raw);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function replaceTemplate(template, values) {
  return Object.entries(values).reduce((result, [key, value]) => result.replace(`{${key}}`, String(value)), template);
}

function isTeacher() {
  return currentRole === "teacher";
}

function canManage() {
  return !!workspaceData.can_manage;
}

function currentClassroom() {
  return workspaceData.classroom || allClassrooms.find((item) => String(item.id || "") === currentClassId) || null;
}

function getMeeting(meetingId) {
  return (workspaceData.meetings || []).find((item) => item.meeting_id === meetingId) || null;
}

function getHomework(homeworkId) {
  return (workspaceData.homework || []).find((item) => item.id === homeworkId) || null;
}

function drawerOpen(drawer) {
  if (!drawer) return;
  if (typeof drawer.openDrawer === "function") {
    drawer.openDrawer();
    return;
  }
  drawer.setAttribute("open", "");
}

function drawerClose(drawer) {
  if (!drawer) return;
  if (typeof drawer.close === "function") {
    drawer.close();
    return;
  }
  if (typeof drawer.closeDrawer === "function") {
    drawer.closeDrawer();
    return;
  }
  drawer.removeAttribute("open");
}

function showToast(message, type = "success") {
  BuiltinToast.show(message, { type });
}

function statusLabel(status) {
  return d().statuses[status] || status || "";
}

function roleLabel(role) {
  return role === "teacher" ? d().roleTeacher : d().roleStudent;
}

function attachmentUrl(file) {
  if (file.url) return file.url;
  if (file.filename) return `/api/classroom/${encodeURIComponent(currentClassId)}/files/${encodeURIComponent(file.filename)}`;
  return "#";
}

function submissionCountText(count) {
  return currentLang === "en" ? `${count} submissions` : `${count} 份提交`;
}

function attachmentKind(file) {
  const name = String(file.filename || "").toLowerCase();
  if (/\.(png|jpg|jpeg|gif|webp|svg)$/.test(name)) return "image";
  if (/\.(mp3|wav|ogg|mp4|mov|webm)$/.test(name)) return "media";
  if (/\.(pdf|doc|docx|ppt|pptx|xls|xlsx|txt|md)$/.test(name)) return "doc";
  return "other";
}

function collectSharedFiles(messages) {
  const items = [];
  for (const message of messages) {
    const attachments = Array.isArray(message.attachments) ? message.attachments : [];
    for (const file of attachments) {
      items.push({
        ...file,
        message_id: String(message.id || ""),
        sender_name: String(message.sender_name || message.sender_id || d().unknownUser),
        timestamp: message.timestamp || message.created_at || message.date,
        kind: attachmentKind(file),
      });
    }
  }
  return items;
}

function updateFileChip() {
  const chip = $("file-chip");
  if (selectedFile) {
    chip.classList.add("visible");
    $("file-chip-name").textContent = selectedFile.name;
  } else {
    chip.classList.remove("visible");
    $("file-chip-name").textContent = "";
  }
}

function updateRoomStats(partial) {
  const stats = roomStats.get(currentClassId) || {};
  roomStats.set(currentClassId, { ...stats, ...partial });
}

function roomSubtitleText() {
  const stats = roomStats.get(currentClassId) || {};
  const classroom = currentClassroom();
  const counts = [
    `${stats.members || 0} ${d().memberCount}`,
    `${stats.messages || 0} ${d().messageCount}`,
    `${(workspaceData.meetings || []).length} ${currentLang === "en" ? "sessions" : "场课堂"}`,
  ];
  if (classroom?.teacher_id) {
    counts.unshift(`${roleLabel(isTeacher() ? "teacher" : "student")} · ${escapeHtml(classroom.teacher_id)}`);
  }
  return counts.join(" · ");
}

function renderRoomList() {
  const host = $("room-list");
  if (!allClassrooms.length) {
    host.innerHTML = `<div class="thread-empty"><strong>${escapeHtml(d().roomEmpty)}</strong><div class="room-preview">${escapeHtml(d().roomEmptyDesc)}</div></div>`;
    return;
  }
  host.innerHTML = allClassrooms.map((room) => {
    const roomId = String(room.id || "");
    const stats = roomStats.get(roomId) || {};
    const active = roomId === currentClassId;
    return `
      <button type="button" class="room-row ${active ? "active" : ""}" data-room-id="${escapeHtml(roomId)}">
        <div class="room-name"># ${escapeHtml(room.name || roomId)}</div>
        <div class="room-preview">${escapeHtml(room.description || d().roomMeta)}</div>
        <div class="room-meta">${escapeHtml(`${stats.members || 0} ${d().memberCount} · ${stats.messages || 0} ${d().messageCount}`)}</div>
      </button>
    `;
  }).join("");
  host.querySelectorAll("[data-room-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextClassId = String(button.getAttribute("data-room-id") || "");
      if (!nextClassId || nextClassId === currentClassId) return;
      currentClassId = nextClassId;
      history.replaceState({}, "", `?class_id=${encodeURIComponent(currentClassId)}`);
      activeMeetingId = "";
      meetingMinimized = false;
      hideMeetingStage();
      renderRoomList();
      await loadCurrentRoom();
    });
  });
}

function renderMembers(members) {
  const host = $("member-list");
  if (!members.length) {
    host.innerHTML = `<div class="member-meta">${escapeHtml(d().noMembers)}</div>`;
    return;
  }
  host.innerHTML = members.map((member) => `
    <div class="meeting-card">
      <strong>${escapeHtml(member.name || member.user_id || d().unknownUser)}</strong>
      <div class="member-meta">${escapeHtml(roleLabel(member.role || "student"))}${member.grade ? ` · ${escapeHtml(member.grade)}` : ""}</div>
    </div>
  `).join("");
}

function renderSharedFiles(messages) {
  const host = $("shared-files");
  const files = collectSharedFiles(messages);
  const filtered = currentFileFilter === "all" ? files : files.filter((item) => item.kind === currentFileFilter);
  $("file-filter-empty").textContent = files.length
    ? replaceTemplate(d().fileShowing, { count: filtered.length, total: files.length })
    : "";
  if (!filtered.length) {
    host.innerHTML = `<div class="member-meta">${escapeHtml(files.length ? d().noFilesInFilter : d().noFiles)}</div>`;
    return;
  }
  host.innerHTML = filtered.map((file) => `
    <div class="attachment-card">
      <div>
        <div class="search-result-title">${escapeHtml(file.filename || "file")}</div>
        <div class="member-meta">${escapeHtml(file.sender_name)} · ${escapeHtml(formatStamp(file.timestamp))}</div>
      </div>
      <div class="meeting-actions">
        <a class="ghost-btn" href="${escapeHtml(attachmentUrl(file))}" target="_blank" rel="noreferrer">Open</a>
        <button type="button" class="file-jump-btn" data-jump-message="${escapeHtml(file.message_id)}">${escapeHtml(d().jumpToMessage)}</button>
      </div>
    </div>
  `).join("");
  host.querySelectorAll("[data-jump-message]").forEach((button) => {
    button.addEventListener("click", () => jumpToMessage(String(button.getAttribute("data-jump-message") || "")));
  });
}

function eventCardActions(message) {
  const payload = message.payload || {};
  if (payload.meeting_id) {
    const meeting = getMeeting(payload.meeting_id);
    if (meeting?.room_id || meeting?.create_token) {
      return `<button type="button" class="ghost-btn" data-open-meeting="${escapeHtml(payload.meeting_id)}">${escapeHtml(meeting.room_id ? d().openMeeting : d().startMeeting)}</button>`;
    }
  }
  if (payload.homework_id && !isTeacher()) {
    return `<button type="button" class="ghost-btn" data-submit-homework="${escapeHtml(payload.homework_id)}">${escapeHtml(d().submitHomework)}</button>`;
  }
  return "";
}

function renderSystemMessage(message) {
  const payload = message.payload || {};
  return `
    <div class="system-event-card">
      <span class="status-pill ${escapeHtml(payload.status || "scheduled")}">${escapeHtml(message.kind?.includes("meeting") ? d().meetingNotice : d().homeworkNotice)}</span>
      <strong>${escapeHtml(message.text || "")}</strong>
      <div class="system-event-meta">${escapeHtml(formatStamp(message.timestamp || message.created_at || message.date))}</div>
      <div class="system-event-actions">${eventCardActions(message)}</div>
    </div>
  `;
}

function renderMessageAttachments(message) {
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  if (!attachments.length) return "";
  return `
    <div class="message-attachments">
      ${attachments.map((file) => `
        <div class="attachment-card">
          <div>
            <div class="search-result-title">${escapeHtml(file.filename || "file")}</div>
            <div class="member-meta">${escapeHtml(d().fileSelected)}</div>
          </div>
          <a class="ghost-btn" href="${escapeHtml(attachmentUrl(file))}" target="_blank" rel="noreferrer">Open</a>
        </div>
      `).join("")}
    </div>
  `;
}

function renderMessages(messages) {
  const host = $("chat-messages");
  if (!messages.length) {
    host.innerHTML = `<div class="thread-empty">${escapeHtml(d().noMessages)}</div>`;
    return;
  }

  let lastDay = "";
  let lastSender = "";
  host.innerHTML = messages.map((message) => {
    const timestamp = message.timestamp || message.created_at || message.date;
    const currentDay = dayKey(timestamp);
    const showDay = currentDay !== lastDay;
    const isSelf = String(message.sender_id || "") === currentUserId;
    const compact = !showDay && lastSender === String(message.sender_id || "") && !message.kind;
    lastDay = currentDay;
    lastSender = String(message.sender_id || "");
    const avatar = (message.sender_name || message.sender_id || d().unknownUser).slice(0, 1).toUpperCase();
    return `
      ${showDay ? `<div class="message-day-divider">${escapeHtml(formatDayLabel(timestamp))}</div>` : ""}
      <div class="message-row ${isSelf ? "self" : ""} ${compact ? "compact" : ""}" data-message-id="${escapeHtml(message.id || "")}">
        <div class="message-avatar">${escapeHtml(avatar)}</div>
        <div class="message-card">
          ${message.kind ? renderSystemMessage(message) : `
            <div class="message-head">
              <div class="message-author">${escapeHtml(message.sender_name || message.sender_id || d().unknownUser)}</div>
              <div class="message-time">${escapeHtml(formatStamp(timestamp))}</div>
            </div>
            <div class="message-body">${escapeHtml(message.text || "")}</div>
            ${renderMessageAttachments(message)}
          `}
        </div>
      </div>
    `;
  }).join("");

  host.querySelectorAll("[data-open-meeting]").forEach((button) => {
    button.addEventListener("click", () => openMeetingStage(String(button.getAttribute("data-open-meeting") || "")));
  });
  host.querySelectorAll("[data-submit-homework]").forEach((button) => {
    button.addEventListener("click", () => openSubmissionDrawer(String(button.getAttribute("data-submit-homework") || "")));
  });
}

function renderThreadBanner() {
  const host = $("thread-banner");
  const liveMeeting = (workspaceData.meetings || []).find((item) => item.status === "live");
  const nextMeeting = (workspaceData.meetings || []).find((item) => item.status !== "live" && item.status !== "ended");
  const nextHomework = (workspaceData.homework || []).find((item) => item.status !== "graded");
  const cards = [];

  if (liveMeeting) {
    cards.push(`
      <div class="banner-card">
        <span class="status-pill live">${escapeHtml(d().liveMeeting)}</span>
        <strong>${escapeHtml(liveMeeting.title)}</strong>
        <div class="banner-meta">${escapeHtml(formatShortDate(liveMeeting.started_at || liveMeeting.scheduled_at))}</div>
        <div class="banner-actions"><button type="button" class="ghost-btn" data-open-meeting="${escapeHtml(liveMeeting.meeting_id)}">${escapeHtml(d().openMeeting)}</button></div>
      </div>
    `);
  }

  if (nextMeeting) {
    cards.push(`
      <div class="banner-card">
        <span class="status-pill scheduled">${escapeHtml(d().nextMeeting)}</span>
        <strong>${escapeHtml(nextMeeting.title)}</strong>
        <div class="banner-meta">${escapeHtml(formatShortDate(nextMeeting.scheduled_at))}</div>
        <div class="banner-actions"><button type="button" class="ghost-btn" data-open-meeting="${escapeHtml(nextMeeting.meeting_id)}">${escapeHtml(nextMeeting.room_id ? d().openMeeting : d().startMeeting)}</button></div>
      </div>
    `);
  }

  if (nextHomework) {
    cards.push(`
      <div class="banner-card">
        <span class="status-pill ${escapeHtml(nextHomework.status || "pending")}">${escapeHtml(d().upcomingHomework)}</span>
        <strong>${escapeHtml(nextHomework.title)}</strong>
        <div class="banner-meta">${escapeHtml(formatShortDate(nextHomework.due_at))}</div>
        <div class="banner-actions">${!isTeacher() ? `<button type="button" class="ghost-btn" data-submit-homework="${escapeHtml(nextHomework.id)}">${escapeHtml(nextHomework.submission ? d().updateSubmission : d().submitHomework)}</button>` : ""}</div>
      </div>
    `);
  }

  host.innerHTML = cards.length ? `<div class="banner-grid">${cards.join("")}</div>` : "";
  host.querySelectorAll("[data-open-meeting]").forEach((button) => {
    button.addEventListener("click", () => openMeetingStage(String(button.getAttribute("data-open-meeting") || "")));
  });
  host.querySelectorAll("[data-submit-homework]").forEach((button) => {
    button.addEventListener("click", () => openSubmissionDrawer(String(button.getAttribute("data-submit-homework") || "")));
  });
}

function renderTimelineList() {
  const host = $("timeline-list");
  const items = (workspaceData.calendar || []).slice(0, 6);
  if (!items.length) {
    host.innerHTML = `<div class="timeline-empty">${escapeHtml(d().timelineEmpty)}</div>`;
    return;
  }
  host.innerHTML = items.map((item) => `
    <div class="timeline-card">
      <span class="status-pill ${escapeHtml(item.status || "scheduled")}">${escapeHtml(item.kind === "meeting" ? d().meetingNotice : d().homeworkNotice)}</span>
      <strong>${escapeHtml(item.title)}</strong>
      <div class="timeline-meta">${escapeHtml(formatShortDate(item.start))}</div>
      <div class="meeting-actions">
        ${item.kind === "meeting"
          ? `<button type="button" class="ghost-btn" data-open-meeting="${escapeHtml(item.target_id)}">${escapeHtml(d().openMeeting)}</button>`
          : (!isTeacher() ? `<button type="button" class="ghost-btn" data-submit-homework="${escapeHtml(item.target_id)}">${escapeHtml(d().submitHomework)}</button>` : "")}
      </div>
    </div>
  `).join("");
  host.querySelectorAll("[data-open-meeting]").forEach((button) => {
    button.addEventListener("click", () => openMeetingStage(String(button.getAttribute("data-open-meeting") || "")));
  });
  host.querySelectorAll("[data-submit-homework]").forEach((button) => {
    button.addEventListener("click", () => openSubmissionDrawer(String(button.getAttribute("data-submit-homework") || "")));
  });
}

function renderHomeworkPanel() {
  const host = $("homework-list-panel");
  const items = workspaceData.homework || [];
  if (!items.length) {
    host.innerHTML = `<div class="homework-empty">${escapeHtml(d().homeworkEmpty)}</div>`;
    return;
  }
  host.innerHTML = items.map((item) => `
    <div class="homework-card">
      <span class="status-pill ${escapeHtml(item.status || "pending")}">${escapeHtml(statusLabel(item.status))}</span>
      <strong>${escapeHtml(item.title)}</strong>
      <div class="homework-meta">${escapeHtml(item.description || "")}</div>
      <div class="homework-meta">${escapeHtml(formatShortDate(item.due_at))}</div>
      <div class="homework-actions">
        ${isTeacher()
          ? `<span class="member-meta">${escapeHtml(submissionCountText(item.submission_count || 0))}</span><button type="button" class="ghost-btn" data-review-homework="${escapeHtml(item.id)}">${escapeHtml(d().submissionReviewAction)}</button>`
          : `<button type="button" class="ghost-btn" data-submit-homework="${escapeHtml(item.id)}">${escapeHtml(item.submission ? d().updateSubmission : d().submitHomework)}</button>`}
      </div>
    </div>
  `).join("");
  host.querySelectorAll("[data-submit-homework]").forEach((button) => {
    button.addEventListener("click", () => openSubmissionDrawer(String(button.getAttribute("data-submit-homework") || "")));
  });
  host.querySelectorAll("[data-review-homework]").forEach((button) => {
    button.addEventListener("click", () => openHomeworkReviewDrawer(String(button.getAttribute("data-review-homework") || "")));
  });
}

function openHomeworkReviewDrawer(homeworkId) {
  if (!isTeacher()) return;
  const homework = getHomework(homeworkId);
  if (!homework) return;
  activeReviewHomeworkId = homeworkId;

  const submissions = Array.isArray(homework.submissions) ? homework.submissions : [];
  $("homework-review-summary").textContent = `${homework.title} · ${formatShortDate(homework.due_at)} · ${submissionCountText(submissions.length)}`;

  const host = $("homework-review-list");
  if (!submissions.length) {
    host.innerHTML = `<div class="homework-empty">${escapeHtml(d().submissionReviewEmpty)}</div>`;
    drawerOpen($("homework-review-drawer"));
    return;
  }

  host.innerHTML = submissions.map((submission) => {
    const reviewed = submission.grade != null || !!String(submission.feedback || "").trim();
    const gradeText = !reviewed ? d().submissionNoGrade : (submission.grade == null ? statusLabel("graded") : `${statusLabel("graded")} · ${submission.grade}`);
    return `
      <div class="homework-review-card">
        <span class="status-pill ${escapeHtml(reviewed ? "graded" : "submitted")}">${escapeHtml(gradeText)}</span>
        <strong>${escapeHtml(submission.student_name || submission.student_id || d().unknownUser)}</strong>
        <div class="homework-meta">${escapeHtml(d().submissionStudentLabel)} · ${escapeHtml(submission.student_id || "")}</div>
        <div class="homework-meta">${escapeHtml(d().submissionSubmittedAt)} · ${escapeHtml(formatShortDate(submission.created_at))}</div>
        <div class="homework-meta">${escapeHtml(submission.filename || "")}</div>
        <form class="drawer-form" data-review-form data-homework-id="${escapeHtml(homeworkId)}" data-submission-id="${escapeHtml(submission.submission_id || "")}">
          <label>
            <div class="field-label">${escapeHtml(d().submissionGradeLabel)}</div>
            <input class="field-input" name="grade" type="text" value="${escapeHtml(submission.grade ?? "")}">
          </label>
          <label>
            <div class="field-label">${escapeHtml(d().submissionFeedbackLabel)}</div>
            <textarea class="field-textarea" name="feedback">${escapeHtml(submission.feedback || "")}</textarea>
          </label>
          <div class="homework-actions">
            ${submission.url ? `<a class="ghost-btn" href="${escapeHtml(submission.url)}" target="_blank" rel="noreferrer">${escapeHtml(d().submissionDownload)}</a>` : ""}
            <button type="submit" class="ghost-btn">${escapeHtml(d().submissionReviewSave)}</button>
          </div>
        </form>
      </div>
    `;
  }).join("");
  host.querySelectorAll("[data-review-form]").forEach((form) => {
    form.addEventListener("submit", submitHomeworkReview);
  });
  drawerOpen($("homework-review-drawer"));
}

async function submitHomeworkReview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submissionId = String(form.getAttribute("data-submission-id") || "");
  const homeworkId = String(form.getAttribute("data-homework-id") || activeReviewHomeworkId || "");
  if (!submissionId) return;

  const formData = new FormData(form);
  const grade = String(formData.get("grade") || "").trim();
  const feedback = String(formData.get("feedback") || "").trim();
  const response = await api(`/classroom/${currentClassId}/workspace`, {
    method: "POST",
    body: JSON.stringify({
      action: "review_submission",
      submission_id: submissionId,
      grade,
      feedback,
    }),
  });
  if (!response || response.ok === false) {
    showToast(response?.error || d().sendFailed, "error");
    return;
  }
  await loadWorkspace();
  openHomeworkReviewDrawer(homeworkId);
  showToast(d().submissionReviewSaved);
}

function renderMeetingLists() {
  const meetingHost = $("meeting-list");
  const dockHost = $("meeting-dock-list");
  const items = workspaceData.meetings || [];
  if (!items.length) {
    meetingHost.innerHTML = `<div class="meeting-empty">${escapeHtml(d().meetingEmpty)}</div>`;
    dockHost.innerHTML = `<div class="meeting-dock-empty">${escapeHtml(d().meetingDockEmpty)}</div>`;
  } else {
    const html = items.map((item) => `
      <div class="meeting-card ${item.status === "live" ? "live" : ""}">
        <span class="status-pill ${escapeHtml(item.status || "scheduled")}">${escapeHtml(statusLabel(item.status))}</span>
        <strong>${escapeHtml(item.title)}</strong>
        <div class="meeting-meta">${escapeHtml(item.description || d().scheduleHint)}</div>
        <div class="meeting-meta">${escapeHtml(formatShortDate(item.started_at || item.scheduled_at))}</div>
        <div class="meeting-actions">
          <button type="button" class="ghost-btn" data-open-meeting="${escapeHtml(item.meeting_id)}">${escapeHtml(item.room_id ? d().openMeeting : d().startMeeting)}</button>
          ${item.can_manage && item.status === "live" ? `<button type="button" class="ghost-btn" data-end-meeting="${escapeHtml(item.meeting_id)}">${escapeHtml(d().endMeetingAction)}</button>` : ""}
        </div>
      </div>
    `).join("");
    meetingHost.innerHTML = html;
    dockHost.innerHTML = html.replaceAll("meeting-card", "meeting-dock-item");
  }

  for (const host of [meetingHost, dockHost]) {
    host.querySelectorAll("[data-open-meeting]").forEach((button) => {
      button.addEventListener("click", () => openMeetingStage(String(button.getAttribute("data-open-meeting") || "")));
    });
    host.querySelectorAll("[data-end-meeting]").forEach((button) => {
      button.addEventListener("click", () => endMeeting(String(button.getAttribute("data-end-meeting") || "")));
    });
  }

  const chip = $("meeting-minimized-chip");
  if (meetingMinimized && activeMeetingId) {
    const meeting = getMeeting(activeMeetingId);
    if (meeting) {
      chip.hidden = false;
      chip.textContent = `${d().openMeeting} · ${meeting.title}`;
    }
  } else {
    chip.hidden = true;
    chip.textContent = "";
  }
}

function renderWhiteboardPreview() {
  const host = $("whiteboard-preview-panel");
  const latest = (workspaceData.meetings || []).find((item) => item.whiteboard_snapshot);
  if (!latest?.whiteboard_snapshot) {
    host.innerHTML = `<div class="whiteboard-empty" style="padding:14px;">${escapeHtml(d().whiteboardEmpty)}</div>`;
    return;
  }
  host.innerHTML = `
    <img src="${escapeHtml(latest.whiteboard_snapshot)}" alt="whiteboard snapshot">
    <div style="padding: 12px;" class="whiteboard-meta">${escapeHtml(latest.title)} · ${escapeHtml(formatShortDate(latest.whiteboard_updated_at || latest.scheduled_at))}</div>
  `;
}

function renderWorkspace() {
  const classroom = currentClassroom();
  $("room-title").textContent = classroom?.name || d().sidebarTitle;
  $("info-room-name").textContent = classroom?.name || d().sidebarTitle;
  $("room-subtitle").textContent = roomSubtitleText();
  $("info-room-meta").textContent = `${d().roomMeta}${workspaceData.homework?.length ? ` · ${workspaceData.homework.length}` : ""}`;

  const calendar = $("class-calendar");
  calendar.events = workspaceData.calendar || [];

  $("btn-live-class").hidden = !canManage();
  $("btn-schedule-class").hidden = !canManage();
  $("btn-open-planner").hidden = !canManage();

  renderThreadBanner();
  renderTimelineList();
  renderHomeworkPanel();
  renderMeetingLists();
  renderWhiteboardPreview();
  renderMeetingStage();
}

function renderMeetingStage() {
  const stage = $("meeting-stage");
  const meeting = getMeeting(activeMeetingId);
  if (!meeting || meetingMinimized) {
    stage.hidden = true;
    $("meeting-frame").removeAttribute("src");
    return;
  }

  stage.hidden = false;
  $("meeting-stage-title").textContent = meeting.title || d().meetingStageTitle;
  $("meeting-stage-meta").textContent = `${statusLabel(meeting.status)} · ${formatShortDate(meeting.started_at || meeting.scheduled_at)}`;
  $("btn-end-meeting").hidden = !(meeting.can_manage && meeting.status === "live");
  $("btn-broadcast-whiteboard").hidden = !meeting.can_manage;
  setMeetingTab(meetingStageTab);

  const frame = $("meeting-frame");
  const nextSrc = buildMeetingSrc(meeting);
  if (nextSrc && frame.dataset.src !== nextSrc) {
    frame.dataset.src = nextSrc;
    frame.src = nextSrc;
  }
  if (!nextSrc) {
    frame.removeAttribute("src");
  }

  const whiteboard = $("meeting-whiteboard");
  const viewer = $("meeting-whiteboard-viewer");
  if (meeting.can_manage) {
    whiteboard.hidden = false;
    viewer.hidden = true;
  } else {
    whiteboard.hidden = true;
    viewer.hidden = false;
    viewer.innerHTML = meeting.whiteboard_snapshot
      ? `<img src="${escapeHtml(meeting.whiteboard_snapshot)}" alt="whiteboard snapshot"><div class="whiteboard-meta">${escapeHtml(d().whiteboardStudentHint)}</div>`
      : `<div class="whiteboard-empty">${escapeHtml(d().whiteboardEmpty)}</div>`;
  }
}

function buildMeetingSrc(meeting) {
  if (meeting.room_id) {
    return `/rtc-room.html?room_id=${encodeURIComponent(meeting.room_id)}&user_id=${encodeURIComponent(currentUserId)}&class_id=${encodeURIComponent(currentClassId)}`;
  }
  if (meeting.create_token) {
    return `/rtc-room.html?mode=create&create_token=${encodeURIComponent(meeting.create_token)}&user_id=${encodeURIComponent(currentUserId)}&class_id=${encodeURIComponent(currentClassId)}`;
  }
  return "";
}

function setMeetingTab(tab) {
  meetingStageTab = tab;
  $("meeting-pane-call").classList.toggle("active", tab === "call");
  $("meeting-pane-whiteboard").classList.toggle("active", tab === "whiteboard");
}

function hideMeetingStage() {
  $("meeting-stage").hidden = true;
  $("meeting-frame").removeAttribute("src");
  $("meeting-frame").dataset.src = "";
}

function openMeetingStage(meetingId) {
  const meeting = getMeeting(meetingId);
  if (!meeting) return;
  if (!meeting.room_id && !meeting.create_token && !meeting.join_token) {
    showToast(d().meetingNotReady, "error");
    return;
  }
  activeMeetingId = meetingId;
  meetingMinimized = false;
  meetingStageTab = "call";
  renderMeetingLists();
  renderMeetingStage();
}

function minimizeMeetingStage() {
  if (!activeMeetingId) return;
  meetingMinimized = true;
  renderMeetingLists();
  renderMeetingStage();
}

function restoreMeetingStage() {
  if (!activeMeetingId) return;
  meetingMinimized = false;
  renderMeetingLists();
  renderMeetingStage();
}

function openPlannerDrawer(mode, options = {}) {
  if (!canManage()) return;
  $("planner-type").value = mode;
  $("planner-title").value = options.title || "";
  $("planner-description").value = options.description || "";
  $("planner-due-at").value = options.date ? toDatetimeLocal(options.date) : "";
  $("planner-scheduled-at").value = options.date ? toDatetimeLocal(options.date) : "";
  $("planner-meeting-mode").value = options.instant ? "instant" : "scheduled";
  syncPlannerFields();
  drawerOpen($("planner-drawer"));
}

function syncPlannerFields() {
  const type = $("planner-type").value;
  const meetingMode = $("planner-meeting-mode").value;
  $("planner-due-field").hidden = type !== "homework";
  $("planner-scheduled-field").hidden = type !== "meeting" || meetingMode === "instant";
  $("planner-meeting-mode-field").hidden = type !== "meeting";
}

async function submitPlanner(event) {
  event.preventDefault();
  const type = $("planner-type").value;
  const title = $("planner-title").value.trim();
  if (!title) return;

  const payload = type === "homework"
    ? {
        action: "create_homework",
        title,
        description: $("planner-description").value.trim(),
        due_at: $("planner-due-at").value || null,
      }
    : {
        action: "create_meeting",
        title,
        description: $("planner-description").value.trim(),
        scheduled_at: $("planner-scheduled-at").value || null,
        meeting_mode: $("planner-meeting-mode").value,
      };

  const response = await api(`/classroom/${currentClassId}/workspace`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!response || response.ok === false) {
    showToast(response?.error || d().sendFailed, "error");
    return;
  }

  drawerClose($("planner-drawer"));
  $("planner-form").reset();
  syncPlannerFields();
  await Promise.all([loadWorkspace(), loadChat()]);
  showToast(type === "homework" ? d().homeworkCreated : d().meetingCreated);
  if (type === "meeting" && response.meeting?.meeting_id) {
    // Sync with backend RTC
    if (payload.meeting_mode === "instant") {
      await api(`/classroom/${currentClassId}/rtc/start`, { method: "POST" });
    }
    openMeetingStage(response.meeting.meeting_id);
  }
}

function openSubmissionDrawer(homeworkId) {
  const homework = getHomework(homeworkId);
  if (!homework) return;
  pendingSubmissionHomeworkId = homeworkId;
  $("submission-summary").textContent = `${homework.title} · ${formatShortDate(homework.due_at)}`;
  drawerOpen($("submission-drawer"));
}

async function submitHomework(event) {
  event.preventDefault();
  const file = $("submission-file").files?.[0] || null;
  if (!file) {
    showToast(d().missingFile, "error");
    return;
  }
  const homework = getHomework(pendingSubmissionHomeworkId);
  if (!homework) return;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("student_id", currentUserId);
  formData.append("class_id", currentClassId);
  formData.append("homework_id", pendingSubmissionHomeworkId);
  const token = localStorage.getItem("eclass_token");
  const response = await fetch("/api/student/homework/upload", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  const payload = await response.json().catch(() => null);
  if (!payload || payload.ok === false) {
    showToast(payload?.error || d().sendFailed, "error");
    return;
  }

  const note = $("submission-text").value.trim();
  if (note) {
    await api(`/classroom/${currentClassId}/chat`, {
      method: "POST",
      body: JSON.stringify({ text: `${homework.title}: ${note}` }),
    });
  }

  drawerClose($("submission-drawer"));
  $("submission-form").reset();
  pendingSubmissionHomeworkId = "";
  await Promise.all([loadWorkspace(), loadChat()]);
  showToast(d().submissionSuccess);
}

async function sendMessage() {
  const text = $("chat-input").value.trim();
  if (!text && !selectedFile) return;

  if (selectedFile) {
    const formData = new FormData();
    if (text) formData.append("text", text);
    formData.append("file", selectedFile);
    const token = localStorage.getItem("eclass_token");
    const response = await fetch(`/api/classroom/${currentClassId}/chat`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    const payload = await response.json().catch(() => null);
    if (!payload || payload.ok === false) {
      showToast(payload?.error || d().sendFailed, "error");
      return;
    }
  } else {
    const payload = await api(`/classroom/${currentClassId}/chat`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    if (!payload || payload.ok === false) {
      showToast(payload?.error || d().sendFailed, "error");
      return;
    }
  }

  $("chat-input").value = "";
  $("chat-file").value = "";
  selectedFile = null;
  updateFileChip();
  await loadChat();
}

async function runSearch() {
  const query = $("search-input").value.trim();
  const host = $("search-results");
  if (!query) {
    host.innerHTML = `<div class="search-empty">${escapeHtml(d().searchPlaceholder)}</div>`;
    return;
  }

  const response = await api(`/classroom/${currentClassId}/chat?q=${encodeURIComponent(query)}`);
  const results = (response && response.messages) || [];
  if (!results.length) {
    host.innerHTML = `<div class="search-empty">${escapeHtml(d().searchEmpty)}</div>`;
    return;
  }

  host.innerHTML = results.map((message) => `
    <button type="button" class="search-result-item" data-id="${escapeHtml(message.id || "")}">
      <div class="search-result-title">${escapeHtml(message.sender_name || message.sender_id || d().unknownUser)}</div>
      <div class="search-result-meta">${escapeHtml(formatStamp(message.timestamp || message.created_at || message.date))}</div>
      <div class="member-meta">${escapeHtml(message.text || "")}</div>
    </button>
  `).join("");

  host.querySelectorAll(".search-result-item").forEach((button) => {
    button.addEventListener("click", () => {
      const messageId = button.getAttribute("data-id") || "";
      jumpToMessage(messageId);
      drawerClose($("search-drawer"));
    });
  });
}

async function loadClassrooms() {
  const response = await api("/classroom/list");
  allClassrooms = Array.isArray(response?.classrooms) ? response.classrooms : [];
  if (!allClassrooms.find((item) => String(item.id || "") === currentClassId) && allClassrooms[0]) {
    currentClassId = String(allClassrooms[0].id || currentClassId);
  }
  renderRoomList();
}

async function loadMembers() {
  const response = await api(`/classroom/${currentClassId}/members`);
  currentMembers = Array.isArray(response?.members) ? response.members : [];
  updateRoomStats({ members: currentMembers.length });
  renderMembers(currentMembers);
}

async function loadChat() {
  const response = await api(`/classroom/${currentClassId}/chat`);
  currentMessages = Array.isArray(response?.messages) ? response.messages : [];
  updateRoomStats({ messages: currentMessages.length });
  renderMessages(currentMessages);
  renderSharedFiles(currentMessages);
}

async function loadWorkspace() {
  const response = await api(`/classroom/${currentClassId}/workspace`);
  if (!response || response.ok === false) {
    workspaceData = { classroom: null, can_manage: false, homework: [], meetings: [], calendar: [] };
    renderWorkspace();
    return;
  }
  workspaceData = response;
  renderWorkspace();
}

async function loadCurrentRoom() {
  await Promise.all([loadMembers(), loadChat(), loadWorkspace()]);
  renderRoomList();
}

function jumpToMessage(messageId) {
  if (!messageId) return;
  const row = Array.from(document.querySelectorAll("[data-message-id]"))
    .find((item) => item.getAttribute("data-message-id") === messageId);
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.animate([
    { transform: "scale(1)", boxShadow: "0 0 0 rgba(37,99,235,0)" },
    { transform: "scale(1.01)", boxShadow: "0 0 0 6px rgba(37,99,235,0.14)" },
    { transform: "scale(1)", boxShadow: "0 0 0 rgba(37,99,235,0)" },
  ], { duration: 700, easing: "ease-out" });
}

async function endMeeting(meetingId = activeMeetingId) {
  if (!meetingId) return;
  const response = await api(`/classroom/${currentClassId}/workspace`, {
    method: "POST",
    body: JSON.stringify({ action: "end_meeting", meeting_id: meetingId }),
  });
  if (!response || response.ok === false) {
    showToast(response?.error || d().sendFailed, "error");
    return;
  }
  // Sync with backend RTC
  await api(`/classroom/${currentClassId}/rtc/end`, { method: "POST" });
  if (meetingId === activeMeetingId) {
    activeMeetingId = "";
    meetingMinimized = false;
  }
  await Promise.all([loadWorkspace(), loadChat()]);
}

async function broadcastWhiteboardSnapshot() {
  const meeting = getMeeting(activeMeetingId);
  if (!meeting || !meeting.can_manage) return;
  shouldBroadcastWhiteboard = true;
  $("meeting-whiteboard").exportImage();
}

async function handleWhiteboardExport(event) {
  if (!shouldBroadcastWhiteboard) return;
  shouldBroadcastWhiteboard = false;
  const dataURL = event.detail?.dataURL;
  if (!dataURL || !activeMeetingId) return;
  const response = await api(`/classroom/${currentClassId}/workspace`, {
    method: "POST",
    body: JSON.stringify({
      action: "save_whiteboard",
      meeting_id: activeMeetingId,
      whiteboard_snapshot: dataURL,
    }),
  });
  if (!response || response.ok === false) {
    showToast(response?.error || d().sendFailed, "error");
    return;
  }
  await loadWorkspace();
  showToast(d().whiteboardSaved);
}

async function handleMeetingMessage(event) {
  const data = event.data;
  if (!data || data.type !== "event") return;
  if (data.event !== "connected") return;

  const meeting = getMeeting(activeMeetingId);
  if (!meeting || !meeting.can_manage || meeting.room_id || !data.room_id) return;

  const response = await api(`/classroom/${currentClassId}/workspace`, {
    method: "POST",
    body: JSON.stringify({
      action: "activate_meeting",
      meeting_id: activeMeetingId,
      room_id: data.room_id,
      room_password: data.room_password || null,
    }),
  });
  if (!response || response.ok === false) {
    showToast(response?.error || d().sendFailed, "error");
    return;
  }
  await Promise.all([loadWorkspace(), loadChat()]);
}

function applyCopy() {
  $("sidebar-eyebrow").textContent = d().sidebarEyebrow;
  $("sidebar-title").textContent = d().sidebarTitle;
  $("sidebar-copy").textContent = d().sidebarCopy;
  $("meeting-dock-title").textContent = d().meetingDockTitle;
  $("planner-open-label").textContent = d().plannerOpen;
  $("calendar-label").textContent = d().calendar;
  $("live-class-label").textContent = d().liveClass;
  $("schedule-class-label").textContent = d().scheduleClass;
  $("search-label").textContent = d().search;
  $("search-drawer-title").textContent = d().searchTitle;
  $("search-input").placeholder = d().searchPlaceholder;
  $("attach-label").textContent = d().attach;
  $("send-label").textContent = d().send;
  $("btn-logout").textContent = d().logout;
  $("back-label").textContent = isTeacher() ? d().backTeacher : d().backStudent;
  $("btn-back-link").href = isTeacher() ? "teacher.html" : "student.html";
  $("info-room-label").textContent = d().infoRoom;
  $("info-calendar-label").textContent = d().infoCalendar;
  $("info-timeline-label").textContent = d().infoTimeline;
  $("info-homework-label").textContent = d().infoHomework;
  $("info-meetings-label").textContent = d().infoMeetings;
  $("info-whiteboard-label").textContent = d().infoWhiteboard;
  $("info-members-label").textContent = d().infoMembers;
  $("info-files-label").textContent = d().infoFiles;
  $("planner-drawer-title").textContent = d().plannerTitle;
  $("planner-type-label").textContent = d().plannerType;
  $("planner-type").options[0].textContent = d().plannerHomework;
  $("planner-type").options[1].textContent = d().plannerMeeting;
  $("planner-title-label").textContent = d().plannerItemTitle;
  $("planner-description-label").textContent = d().plannerDescription;
  $("planner-due-label").textContent = d().plannerDue;
  $("planner-scheduled-label").textContent = d().plannerScheduled;
  $("planner-mode-label").textContent = d().plannerMode;
  $("planner-meeting-mode").options[0].textContent = d().plannerScheduledMode;
  $("planner-meeting-mode").options[1].textContent = d().plannerInstantMode;
  $("planner-help").textContent = d().plannerHelp;
  $("planner-submit").textContent = d().plannerSubmit;
  $("planner-cancel").textContent = d().plannerCancel;
  $("submission-drawer-title").textContent = d().submissionTitle;
  $("submission-note-label").textContent = d().submissionNote;
  $("submission-file-label").textContent = d().submissionFile;
  $("submission-submit").textContent = d().submissionSubmit;
  $("submission-cancel").textContent = d().submissionCancel;
  $("submission-summary").textContent = d().submissionSummaryEmpty;
  $("homework-review-drawer-title").textContent = d().submissionReviewTitle;
  $("broadcast-whiteboard-label").textContent = d().broadcastWhiteboard;
  $("end-meeting-label").textContent = d().endMeeting;
  $("minimize-meeting-label").textContent = d().minimizeMeeting;
  $("btn-meeting-tab-call").textContent = d().meetingCallTab;
  $("btn-meeting-tab-whiteboard").textContent = d().meetingWhiteboardTab;

  const filters = $("file-filter-row").querySelectorAll("[data-file-filter]");
  const labels = {
    all: d().fileFilterAll,
    image: d().fileFilterImage,
    doc: d().fileFilterDoc,
    media: d().fileFilterMedia,
    other: d().fileFilterOther,
  };
  filters.forEach((button) => {
    const key = button.getAttribute("data-file-filter") || "all";
    button.textContent = labels[key] || key;
  });
}

function setFileFilter(filter) {
  currentFileFilter = filter;
  $("file-filter-row").querySelectorAll("[data-file-filter]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-file-filter") === filter);
  });
  renderSharedFiles(currentMessages);
}

$("file-filter-row").querySelectorAll("[data-file-filter]").forEach((button) => {
  button.addEventListener("click", () => setFileFilter(button.getAttribute("data-file-filter") || "all"));
});

$("btn-chat").addEventListener("click", sendMessage);
$("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});
$("btn-attach").addEventListener("click", () => $("chat-file").click());
$("chat-file").addEventListener("change", (event) => {
  selectedFile = event.target.files?.[0] || null;
  updateFileChip();
});
$("btn-search-toggle").addEventListener("click", () => drawerOpen($("search-drawer")));
$("search-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runSearch();
  }
});
$("btn-calendar").addEventListener("click", () => {
  document.querySelector("#class-calendar")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
$("btn-live-class").addEventListener("click", () => openPlannerDrawer("meeting", { instant: true }));
$("btn-schedule-class").addEventListener("click", () => openPlannerDrawer("meeting"));
$("btn-open-planner").addEventListener("click", () => openPlannerDrawer("homework"));
$("planner-type").addEventListener("change", syncPlannerFields);
$("planner-meeting-mode").addEventListener("change", syncPlannerFields);
$("planner-form").addEventListener("submit", submitPlanner);
$("planner-cancel").addEventListener("click", () => drawerClose($("planner-drawer")));
$("submission-form").addEventListener("submit", submitHomework);
$("submission-cancel").addEventListener("click", () => drawerClose($("submission-drawer")));
$("btn-minimize-meeting").addEventListener("click", minimizeMeetingStage);
$("meeting-minimized-chip").addEventListener("click", restoreMeetingStage);
$("btn-meeting-tab-call").addEventListener("click", () => setMeetingTab("call"));
$("btn-meeting-tab-whiteboard").addEventListener("click", () => setMeetingTab("whiteboard"));
$("btn-end-meeting").addEventListener("click", () => endMeeting(activeMeetingId));
$("btn-broadcast-whiteboard").addEventListener("click", broadcastWhiteboardSnapshot);
$("meeting-whiteboard").addEventListener("builtin-export", handleWhiteboardExport);
$("class-calendar").addEventListener("builtin-event-click", (event) => {
  const item = event.detail?.event;
  if (!item) return;
  if (item.kind === "meeting") {
    openMeetingStage(String(item.target_id || ""));
  } else if (item.kind === "homework" && !isTeacher()) {
    openSubmissionDrawer(String(item.target_id || ""));
  }
});
$("class-calendar").addEventListener("builtin-date-click", (event) => {
  if (!canManage()) return;
  openPlannerDrawer("homework", { date: event.detail?.date || null });
});
$("btn-logout").addEventListener("click", () => {
  localStorage.removeItem("eclass_token");
  localStorage.removeItem("eclass_role");
  localStorage.removeItem("eclass_user");
  location.href = "login.html";
});
window.addEventListener("message", (event) => {
  handleMeetingMessage(event).catch((error) => {
    console.error(error);
  });
});

await shell.init();
applyCopy();
syncPlannerFields();
await loadClassrooms();
await loadCurrentRoom();

pollHandle = setInterval(() => {
  if (document.hidden) return;
  loadChat().catch((error) => console.error(error));
  loadWorkspace().catch((error) => console.error(error));
  // Poll RTC status for participant list
  if (activeMeetingId) {
    api(`/classroom/${currentClassId}/rtc/status`)
      .then((rtc) => {
        if (rtc && rtc.active === false && activeMeetingId) {
          // Meeting ended by teacher
          showToast(d().meetingEnded, "info");
          activeMeetingId = "";
          meetingMinimized = false;
          hideMeetingStage();
          loadWorkspace();
        }
      })
      .catch((error) => console.error(error));
  }
}, 4000);