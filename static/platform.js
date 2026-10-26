/*
 * Shared browser-local learning state for the public platform.
 *
 * Only learning summaries belong here: assessment score/topic totals, read
 * markers, and which tools were used. Quiz answers, calculator inputs, and
 * research-application data are never stored in this key and never uploaded.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "xinyue.learning.v1";
  var SCHEMA_VERSION = 1;
  var PLATFORM_VERSION = "platform-v1";
  var ASSESSMENT_VERSION = "literacy-learning-v1";
  var APPLICATION_SESSION_KEY = "xinyue.original-eight-page.v3";
  var TOOL_KEYS = ["loan", "budget", "anti-fraud"];
  var TOPIC_SLUG = /^[a-z0-9-]{1,64}$/;

  var memoryState = emptyState();
  var storageWorks = canUseStorage();

  function emptyState() {
    return {
      schema: SCHEMA_VERSION,
      platformVersion: PLATFORM_VERSION,
      assessmentVersion: ASSESSMENT_VERSION,
      assessment: null,
      readTopics: {},
      tools: {}
    };
  }

  function canUseStorage() {
    try {
      var probe = "__xinyue_probe__";
      window.localStorage.setItem(probe, "1");
      window.localStorage.removeItem(probe);
      return true;
    } catch (_error) {
      return false;
    }
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function asInteger(value, fallback) {
    var parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
  }

  function cleanAssessment(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    var completed = new Date(raw.completedAt);
    if (Number.isNaN(completed.getTime())) {
      return null;
    }
    var total = asInteger(raw.total, 0);
    if (total < 1 || total > 200) {
      return null;
    }
    var score = Math.min(asInteger(raw.score, 0), total);
    var answered = Math.min(asInteger(raw.answered, 0), total);

    var topics = [];
    if (Array.isArray(raw.topics)) {
      raw.topics.slice(0, 12).forEach(function (topic) {
        if (!topic || typeof topic !== "object") {
          return;
        }
        if (!TOPIC_SLUG.test(String(topic.slug || ""))) {
          return;
        }
        var topicTotal = asInteger(topic.total, 0);
        if (topicTotal < 1) {
          return;
        }
        topics.push({
          slug: String(topic.slug),
          name: String(topic.name || "").slice(0, 40),
          correct: Math.min(asInteger(topic.correct, 0), topicTotal),
          total: topicTotal
        });
      });
    }

    var recommendations = [];
    if (Array.isArray(raw.recommendations)) {
      raw.recommendations.slice(0, 12).forEach(function (item) {
        if (!item || typeof item !== "object") {
          return;
        }
        if (!TOPIC_SLUG.test(String(item.slug || ""))) {
          return;
        }
        recommendations.push({
          slug: String(item.slug),
          name: String(item.name || "").slice(0, 40)
        });
      });
    }

    return {
      version: ASSESSMENT_VERSION,
      completedAt: completed.toISOString(),
      score: score,
      total: total,
      answered: answered,
      topics: topics,
      recommendations: recommendations
    };
  }

  function normalizeState(raw) {
    var state = emptyState();
    if (!raw || typeof raw !== "object") {
      return state;
    }

    if (raw.readTopics && typeof raw.readTopics === "object") {
      Object.keys(raw.readTopics).slice(0, 200).forEach(function (slug) {
        var stamp = raw.readTopics[slug];
        if (TOPIC_SLUG.test(slug) && typeof stamp === "string") {
          state.readTopics[slug] = stamp.slice(0, 40);
        }
      });
    }

    if (raw.tools && typeof raw.tools === "object") {
      TOOL_KEYS.forEach(function (tool) {
        var stamp = raw.tools[tool];
        if (typeof stamp === "string") {
          state.tools[tool] = stamp.slice(0, 40);
        }
      });
    }

    state.assessment = cleanAssessment(raw.assessment);
    return state;
  }

  function loadState() {
    if (!storageWorks) {
      return normalizeState(clone(memoryState));
    }
    var raw;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (_error) {
      storageWorks = false;
      return normalizeState(clone(memoryState));
    }
    if (!raw) {
      return emptyState();
    }
    try {
      return normalizeState(JSON.parse(raw));
    } catch (_error) {
      // A damaged local record should not disable storage for this page.
      return emptyState();
    }
  }

  function commit(nextState) {
    nextState.schema = SCHEMA_VERSION;
    nextState.platformVersion = PLATFORM_VERSION;
    nextState.assessmentVersion = ASSESSMENT_VERSION;
    nextState.updatedAt = new Date().toISOString();
    memoryState = normalizeState(clone(nextState));

    var saved = false;
    if (storageWorks) {
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(memoryState));
        saved = true;
      } catch (_error) {
        storageWorks = false;
      }
    }

    try {
      document.dispatchEvent(
        new CustomEvent("xinyue:learning-changed", {
          detail: { persisted: saved }
        })
      );
    } catch (_error) {
      /* Older browsers without CustomEvent still get an updated UI. */
    }
    return saved;
  }

  function getState() {
    return loadState();
  }

  function storageAvailable() {
    return storageWorks;
  }

  function saveAssessment(summary) {
    var cleaned = cleanAssessment(summary);
    if (!cleaned) {
      return false;
    }
    var next = loadState();
    next.assessment = cleaned;
    return commit(next);
  }

  function markTopicRead(slug) {
    if (!TOPIC_SLUG.test(String(slug || ""))) {
      return false;
    }
    var next = loadState();
    next.readTopics[String(slug)] = new Date().toISOString();
    return commit(next);
  }

  function markToolUsed(tool) {
    if (TOOL_KEYS.indexOf(String(tool || "")) === -1) {
      return false;
    }
    var next = loadState();
    next.tools[String(tool)] = new Date().toISOString();
    return commit(next);
  }

  function clearLearningData() {
    memoryState = emptyState();
    var cleared = false;
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      cleared = true;
    } catch (_error) {
      storageWorks = false;
    }
    try {
      document.dispatchEvent(
        new CustomEvent("xinyue:learning-changed", {
          detail: { persisted: cleared, cleared: true }
        })
      );
    } catch (_error) {
      /* The visible UI is refreshed by the caller. */
    }
    return cleared;
  }

  function readTopicCount(state) {
    return Object.keys(state.readTopics).length;
  }

  function applyIndicators() {
    var state = loadState();
    var count = readTopicCount(state);

    document.querySelectorAll("[data-learning-topic]").forEach(function (node) {
      var slug = node.getAttribute("data-learning-topic");
      var read = Boolean(slug && state.readTopics[slug]);
      node.classList.toggle("is-read", read);
      var badge = node.querySelector(".read-badge");
      if (badge) {
        badge.hidden = !read;
      }
    });

    document.querySelectorAll("[data-learning-read-count]").forEach(function (node) {
      node.textContent = String(count);
    });

    document.querySelectorAll("[data-learning-read-progress]").forEach(function (progress) {
      var max = Number(progress.getAttribute("max"));
      if (!Number.isFinite(max) || max < 1) {
        max = count > 0 ? count : 1;
        progress.setAttribute("max", String(max));
      }
      progress.value = count;
      progress.textContent = count + " / " + max;
    });

    return state;
  }

  function initArticle() {
    var article = document.querySelector("[data-article-topic]");
    if (!article) {
      return;
    }
    var slug = article.getAttribute("data-article-topic");
    var button = article.querySelector("[data-mark-read]");
    var badge = article.querySelector("[data-article-read-badge]");
    var status = article.querySelector("[data-read-status]");

    function syncButton() {
      var read = Boolean(loadState().readTopics[slug]);
      if (badge) {
        badge.hidden = !read;
      }
      if (button) {
        button.disabled = read;
        button.textContent = read ? "已标记为已读" : "标记为已读";
      }
      return read;
    }

    syncButton();
    if (!button) {
      return;
    }
    button.addEventListener("click", function () {
      if (syncButton()) {
        return;
      }
      var persisted = markTopicRead(button.getAttribute("data-topic-slug") || slug);
      syncButton();
      if (status) {
        status.textContent = persisted
          ? "已保存到当前浏览器"
          : "已标记；浏览器本地保存不可用，刷新后可能丢失";
      }
    });
  }

  function initResumeBanner() {
    var banner = document.querySelector("[data-resume-banner]");
    if (!banner) {
      return;
    }
    var hasDraft = false;
    try {
      // Presence only: never read, parse, or transmit the application draft.
      hasDraft = Boolean(window.sessionStorage.getItem(APPLICATION_SESSION_KEY) || window.sessionStorage.getItem("xinyue.original-eight-page.v4"));
    } catch (_error) {
      hasDraft = false;
    }
    if (hasDraft) {
      banner.hidden = false;
    }
  }

  function init() {
    applyIndicators();
    initArticle();
    initResumeBanner();
  }

  window.XinyueLearning = Object.freeze({
    storageKey: STORAGE_KEY,
    platformVersion: PLATFORM_VERSION,
    assessmentVersion: ASSESSMENT_VERSION,
    getState: getState,
    storageAvailable: storageAvailable,
    saveAssessment: saveAssessment,
    markTopicRead: markTopicRead,
    markToolUsed: markToolUsed,
    clearLearningData: clearLearningData,
    applyIndicators: applyIndicators,
    readTopicCount: function () {
      return readTopicCount(loadState());
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
