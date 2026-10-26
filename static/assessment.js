/*
 * Browser-only 16-question learning assessment.
 * Correct answers are scored from data attributes in the rendered page; raw
 * selections are not sent anywhere and are not included in local storage.
 */
(function () {
  "use strict";

  var learning = window.XinyueLearning;
  var form = document.getElementById("assessment-form");
  if (!learning || !form) {
    return;
  }

  var fieldsets = Array.prototype.slice.call(
    form.querySelectorAll(".quiz-question[data-question]")
  );
  if (!fieldsets.length) {
    return;
  }

  var total = Number(form.getAttribute("data-total")) || fieldsets.length;
  var progress = document.getElementById("assessment-progress");
  var countLabel = document.getElementById("assessment-count");
  var submitButton = document.getElementById("assessment-submit-button");
  var resultPanel = document.getElementById("assessment-result");
  var resultScore = document.getElementById("result-score");
  var resultRate = document.getElementById("result-rate");
  var resultSummary = document.getElementById("result-summary");
  var resultCompletion = document.getElementById("result-completion");
  var resultStorageNote = document.getElementById("result-storage-note");
  var resultTopics = document.getElementById("result-topics");
  var resultRecommendations = document.getElementById("result-recommendations");
  var retryButton = document.getElementById("retry-assessment");
  var submitLabel = submitButton ? submitButton.textContent : "查看本次结果";
  var submitted = false;

  function selectedInput(fieldset) {
    return fieldset.querySelector('input[type="radio"]:checked');
  }

  function updateProgress() {
    var answered = fieldsets.filter(function (fieldset) {
      return Boolean(selectedInput(fieldset));
    }).length;
    if (progress) {
      progress.max = total;
      progress.value = answered;
      progress.textContent = answered + " / " + total;
    }
    if (countLabel) {
      countLabel.textContent = "已选择 " + answered + " / " + total + " 题";
    }
    return answered;
  }

  function bindOptionState(fieldset) {
    var labels = Array.prototype.slice.call(
      fieldset.querySelectorAll(".quiz-option")
    );
    labels.forEach(function (label) {
      var input = label.querySelector('input[type="radio"]');
      if (!input) {
        return;
      }
      function sync() {
        labels.forEach(function (other) {
          var otherInput = other.querySelector('input[type="radio"]');
          other.classList.toggle("is-selected", Boolean(otherInput && otherInput.checked));
        });
      }
      input.addEventListener("change", function () {
        sync();
        updateProgress();
      });
      sync();
    });
  }

  function formatRate(percent) {
    var value = Math.round(percent * 10) / 10;
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }

  function formatPercent(part, whole) {
    if (!whole) {
      return "0%";
    }
    return formatRate((part / whole) * 100) + "%";
  }

  function appendRecommendation(container, topic, href) {
    var node;
    if (href) {
      node = document.createElement("a");
      node.href = href;
    } else {
      node = document.createElement("span");
      node.className = "recommend-chip";
    }
    node.textContent = "复习：" + topic.name;
    if (href) {
      var arrow = document.createElement("span");
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = " →";
      node.appendChild(arrow);
    }
    container.appendChild(node);
  }

  function renderResults(score, answered, topicStats, recommendations, links) {
    if (resultScore) {
      resultScore.textContent = String(score);
    }
    if (resultRate) {
      resultRate.textContent = formatPercent(score, total);
    }
    if (resultSummary) {
      if (answered === 0) {
        resultSummary.textContent =
          "本次没有作答题；未作答和“暂不确定”都不会算作正确。";
      } else {
        resultSummary.textContent =
          "本次答对 " + score + " 题，已选择 " + answered + " 题。结果只反映这份学习测验的答题情况。";
      }
    }
    if (resultCompletion) {
      var unanswered = total - answered;
      resultCompletion.textContent =
        "完成度：已选择 " +
        answered +
        " / " +
        total +
        " 题" +
        (unanswered > 0 ? "，未作答 " + unanswered + " 题不计为答对。" : "。" );
    }

    if (resultTopics) {
      resultTopics.textContent = "";
      topicStats.forEach(function (stat) {
        var card = document.createElement("article");
        card.className =
          "result-topic-card" + (stat.correct < stat.total ? " is-weak" : "");

        var head = document.createElement("div");
        head.className = "result-topic-head";
        var name = document.createElement("span");
        name.textContent = stat.name;
        var completion = document.createElement("span");
        completion.textContent = "完成 " + stat.answered + "/" + stat.total;
        head.appendChild(name);
        head.appendChild(completion);

        var value = document.createElement("strong");
        value.textContent = stat.correct + " / " + stat.total;

        var caption = document.createElement("small");
        caption.textContent = "题答对";

        card.appendChild(head);
        card.appendChild(value);
        card.appendChild(caption);
        resultTopics.appendChild(card);
      });
    }

    if (resultRecommendations) {
      resultRecommendations.textContent = "";
      if (recommendations.length) {
        var list = document.createElement("div");
        list.className = "recommend-list";
        recommendations.forEach(function (topic) {
          appendRecommendation(list, topic, links[topic.slug]);
        });
        resultRecommendations.appendChild(list);
      } else {
        var allCorrect = document.createElement("p");
        allCorrect.className = "muted";
        allCorrect.textContent =
          "四个主题本次都答对，可以继续阅读其他主题，或用学习工具做一次实际计算。";
        resultRecommendations.appendChild(allCorrect);
      }
    }
  }

  function scrollToResult() {
    if (!resultPanel) {
      return;
    }
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultPanel.hidden = false;
    if (typeof resultPanel.focus === "function") {
      resultPanel.focus({ preventScroll: true });
    }
    resultPanel.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start"
    });
  }

  function submitAssessment() {
    if (submitted) {
      return;
    }

    var score = 0;
    var answered = 0;
    var topicOrder = [];
    var topicMap = {};
    var learnLinks = {};

    fieldsets.forEach(function (fieldset) {
      var slug = fieldset.getAttribute("data-topic") || "other";
      var topicName = fieldset.getAttribute("data-topic-name") || "其他";
      var correctIndex = fieldset.getAttribute("data-correct");
      var chosen = selectedInput(fieldset);
      var isCorrect = Boolean(chosen && chosen.value === correctIndex);
      var labels = Array.prototype.slice.call(
        fieldset.querySelectorAll(".quiz-option")
      );

      fieldset.classList.remove("is-correct", "is-wrong", "is-unanswered", "is-unsure");

      labels.forEach(function (label) {
        var input = label.querySelector('input[type="radio"]');
        if (!input) {
          return;
        }
        input.disabled = true;
        if (input.value === correctIndex) {
          label.classList.add("is-correct-option");
        }
        if (chosen && input === chosen && !isCorrect) {
          label.classList.add("is-selected-wrong");
        }
      });

      if (chosen) {
        answered += 1;
      }
      if (isCorrect) {
        score += 1;
      }

      var verdict = "";
      if (isCorrect) {
        fieldset.classList.add("is-correct");
        verdict = "回答正确。";
      } else if (!chosen) {
        fieldset.classList.add("is-unanswered");
        verdict = "本题未作答，不计为答对。";
      } else if (chosen.value === "unsure") {
        fieldset.classList.add("is-unsure");
        verdict = "本题选择了“暂不确定”，不计为答对。";
      } else {
        fieldset.classList.add("is-wrong");
        verdict = "本题回答错误。";
      }

      var review = fieldset.querySelector(".answer-review");
      if (review) {
        review.hidden = false;
        var verdictNode = review.querySelector(".review-verdict");
        if (verdictNode) {
          verdictNode.textContent = verdict;
        }
      }

      if (!learnLinks[slug]) {
        var learnAnchor = fieldset.querySelector(".answer-review a");
        if (learnAnchor) {
          learnLinks[slug] = learnAnchor.getAttribute("href");
        }
      }

      if (!topicMap[slug]) {
        topicMap[slug] = {
          slug: slug,
          name: topicName,
          correct: 0,
          answered: 0,
          total: 0
        };
        topicOrder.push(slug);
      }
      topicMap[slug].total += 1;
      if (chosen) {
        topicMap[slug].answered += 1;
      }
      if (isCorrect) {
        topicMap[slug].correct += 1;
      }
    });

    var topicStats = topicOrder.map(function (slug) {
      return topicMap[slug];
    });

    var recommendations = topicStats
      .filter(function (topic) {
        return topic.correct < topic.total;
      })
      .sort(function (left, right) {
        return left.correct / left.total - right.correct / right.total;
      })
      .map(function (topic) {
        return { slug: topic.slug, name: topic.name };
      });

    var persisted = learning.saveAssessment({
      version: learning.assessmentVersion,
      completedAt: new Date().toISOString(),
      score: score,
      total: total,
      answered: answered,
      topics: topicStats.map(function (topic) {
        return {
          slug: topic.slug,
          name: topic.name,
          correct: topic.correct,
          total: topic.total
        };
      }),
      recommendations: recommendations
    });

    renderResults(score, answered, topicStats, recommendations, learnLinks);

    if (resultStorageNote) {
      resultStorageNote.textContent = persisted
        ? "本次摘要已保存在当前浏览器，不会上传服务器。"
        : "浏览器本地存储不可用；本次结果只在当前页面显示。";
    }

    updateProgress();
    submitted = true;
    form.classList.add("is-submitted");
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "本次结果已显示";
    }
    scrollToResult();
  }

  function resetAssessment() {
    fieldsets.forEach(function (fieldset) {
      fieldset.classList.remove("is-correct", "is-wrong", "is-unanswered", "is-unsure");
      var inputs = fieldset.querySelectorAll('input[type="radio"]');
      inputs.forEach(function (input) {
        input.checked = false;
        input.disabled = false;
      });
      fieldset.querySelectorAll(".quiz-option").forEach(function (label) {
        label.classList.remove("is-correct-option", "is-selected-wrong", "is-selected");
      });
      var review = fieldset.querySelector(".answer-review");
      if (review) {
        review.hidden = true;
        var verdict = review.querySelector(".review-verdict");
        if (verdict) {
          verdict.textContent = "";
        }
      }
    });

    submitted = false;
    form.classList.remove("is-submitted");
    if (resultPanel) {
      resultPanel.hidden = true;
    }
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = submitLabel;
    }
    updateProgress();

    var firstInput = form.querySelector('input[type="radio"]');
    if (firstInput) {
      var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      form.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start"
      });
      firstInput.focus({ preventScroll: true });
    }
  }

  fieldsets.forEach(bindOptionState);
  updateProgress();

  if (submitButton) {
    submitButton.addEventListener("click", submitAssessment);
  }
  if (retryButton) {
    retryButton.addEventListener("click", resetAssessment);
  }
})();
