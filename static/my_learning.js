/*
 * Renders the browser-local learning summary. This page never asks the server
 * for learning data and never displays research-application answers.
 */
(function () {
  "use strict";

  var learning = window.XinyueLearning;
  if (!learning) {
    return;
  }

  var emptyPanel = document.getElementById("assessment-record-empty");
  var recordPanel = document.getElementById("assessment-record");
  var rateNode = document.getElementById("my-assessment-rate");
  var scoreNode = document.getElementById("my-assessment-score");
  var totalNode = document.getElementById("my-assessment-total");
  var answeredNode = document.getElementById("my-assessment-answered");
  var dateNode = document.getElementById("my-assessment-date");
  var topicsNode = document.getElementById("my-assessment-topics");
  var recommendationNode = document.getElementById("my-assessment-recommendation");
  var clearButton = document.getElementById("clear-learning-data");
  var clearStatus = document.getElementById("clear-learning-status");

  function formatRate(percent) {
    var value = Math.round(percent * 10) / 10;
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }

  function formatDate(value) {
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    try {
      return new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      }).format(date);
    } catch (_error) {
      return date.toLocaleString();
    }
  }

  function renderAssessment(assessment) {
    if (!assessment) {
      if (emptyPanel) {
        emptyPanel.hidden = false;
      }
      if (recordPanel) {
        recordPanel.hidden = true;
      }
      return;
    }

    if (emptyPanel) {
      emptyPanel.hidden = true;
    }
    if (recordPanel) {
      recordPanel.hidden = false;
    }

    var rate = assessment.total
      ? (assessment.score / assessment.total) * 100
      : 0;
    if (rateNode) {
      rateNode.textContent = formatRate(rate);
    }
    if (scoreNode) {
      scoreNode.textContent = String(assessment.score);
    }
    if (totalNode) {
      totalNode.textContent = String(assessment.total);
    }
    if (answeredNode) {
      answeredNode.textContent = String(assessment.answered);
    }
    if (dateNode) {
      dateNode.textContent = "记录时间：" + formatDate(assessment.completedAt);
    }

    if (topicsNode) {
      topicsNode.textContent = "";
      assessment.topics.forEach(function (topic) {
        var card = document.createElement("div");
        card.className = "record-topic";
        var label = document.createElement("span");
        label.textContent = topic.name || topic.slug;
        var value = document.createElement("strong");
        value.textContent = topic.correct + "/" + topic.total;
        card.appendChild(label);
        card.appendChild(value);
        topicsNode.appendChild(card);
      });
    }

    if (recommendationNode) {
      if (assessment.recommendations.length) {
        var names = assessment.recommendations.map(function (topic) {
          return topic.name || topic.slug;
        });
        recommendationNode.textContent =
          "建议复习：" + names.join("、") + "。可到“知识科普”查看对应主题。";
      } else {
        recommendationNode.textContent =
          "四个主题本次都答对，可以继续阅读其他主题或使用学习工具。";
      }
    }
  }

  function renderTools() {
    var state = learning.getState();
    document.querySelectorAll("[data-tool-record]").forEach(function (item) {
      var key = item.getAttribute("data-tool-record");
      var status = item.querySelector("[data-tool-status]");
      if (!status) {
        return;
      }
      var used = Boolean(state.tools[key]);
      status.textContent = used ? "已使用" : "未使用";
      status.classList.toggle("is-used", used);
      if (used) {
        status.title = "最近使用：" + formatDate(state.tools[key]);
      } else {
        status.removeAttribute("title");
      }
    });
  }

  function renderAll() {
    var state = learning.getState();
    renderAssessment(state.assessment);
    renderTools();
    learning.applyIndicators();
  }

  renderAll();

  if (clearButton) {
    clearButton.addEventListener("click", function () {
      var state = learning.getState();
      var hasData =
        Boolean(state.assessment) ||
        Object.keys(state.readTopics).length > 0 ||
        Object.keys(state.tools).length > 0;

      if (!hasData) {
        if (clearStatus) {
          clearStatus.textContent = "当前浏览器没有可清除的学习记录。";
        }
        return;
      }

      var confirmed = window.confirm(
        "确定清除当前浏览器的测评摘要、阅读标记和工具使用状态吗？此操作不能撤销，但不会影响已经提交的研究记录。"
      );
      if (!confirmed) {
        return;
      }

      learning.clearLearningData();
      if (clearStatus) {
        clearStatus.textContent = "已清除当前浏览器的学习记录。";
      }
      renderAll();
    });
  }
})();
