/*
 * Client-only learning calculators. Inputs stay in this page; only a generic
 * "tool used" marker is written to the browser-local learning record.
 */
(function () {
  "use strict";

  var learning = window.XinyueLearning;
  if (!learning) {
    return;
  }

  var moneyFormatter = new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  function formatMoney(value) {
    return moneyFormatter.format(value);
  }

  function formatPercent(value, digits) {
    var places = Number.isInteger(digits) ? digits : 1;
    var factor = Math.pow(10, places);
    var rounded = Math.round(value * factor) / factor;
    return (
      Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(places)
    ) + "%";
  }

  function round2(value) {
    return Math.round((value + Number.EPSILON) * 100) / 100;
  }

  function showError(node, message) {
    if (!node) {
      return;
    }
    node.textContent = message;
    node.hidden = false;
  }

  function clearError(node) {
    if (!node) {
      return;
    }
    node.textContent = "";
    node.hidden = true;
  }

  function readNumber(id) {
    var input = document.getElementById(id);
    if (!input) {
      return NaN;
    }
    var raw = input.value.trim();
    return raw === "" ? NaN : Number(raw);
  }

  function setText(id, text) {
    var node = document.getElementById(id);
    if (node) {
      node.textContent = text;
    }
  }

  function setBar(barId, value, label) {
    var bar = document.getElementById(barId);
    if (!bar) {
      return;
    }
    var capped = Math.max(0, Math.min(100, value));
    bar.value = capped;
    bar.textContent = label;
  }

  function initLoanCalculator() {
    var button = document.getElementById("loan-calculate");
    if (!button) {
      return;
    }
    var errorNode = document.getElementById("loan-error");
    var principalInput = document.getElementById("loan-principal");
    var monthsInput = document.getElementById("loan-months");
    var rateInput = document.getElementById("loan-rate");

    function calculate() {
      clearError(errorNode);
      var principal = readNumber("loan-principal");
      var months = readNumber("loan-months");
      var annualRate = readNumber("loan-rate");

      if (!Number.isFinite(principal) || principal < 100 || principal > 1000000) {
        showError(errorNode, "借款本金需在 100 元到 1,000,000 元之间。");
        return;
      }
      if (!Number.isInteger(months) || months < 1 || months > 120) {
        showError(errorNode, "期限需为 1 到 120 之间的整数月。");
        return;
      }
      if (!Number.isFinite(annualRate) || annualRate < 0 || annualRate > 60) {
        showError(errorNode, "名义年利率需在 0% 到 60% 之间。");
        return;
      }

      var monthlyRate = annualRate / 100 / 12;
      var rawMonthly;
      if (monthlyRate === 0) {
        rawMonthly = principal / months;
      } else {
        rawMonthly =
          (principal * monthlyRate) /
          (1 - Math.pow(1 + monthlyRate, -months));
      }
      var monthly = round2(rawMonthly);
      var total = round2(rawMonthly * months);
      var interest = Math.max(0, round2(total - principal));
      var effectiveRate = (Math.pow(1 + monthlyRate, 12) - 1) * 100;

      setText("loan-monthly", formatMoney(monthly) + " 元");
      setText("loan-total", formatMoney(total) + " 元");
      setText("loan-interest", formatMoney(interest) + " 元");
      setText("loan-effective", formatPercent(effectiveRate, 2));

      var note = document.getElementById("loan-note");
      if (note) {
        note.textContent =
          "计算口径：月利率 = 名义年利率 ÷ 12；月供按等额本息公式计算，结果四舍五入到分。未计入手续费、保险费、提前还款费用等其他成本。";
      }

      learning.markToolUsed("loan");
    }

    button.addEventListener("click", calculate);
    [principalInput, monthsInput, rateInput].forEach(function (input) {
      if (!input) {
        return;
      }
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          calculate();
        }
      });
    });
  }

  function initBudgetTool() {
    var button = document.getElementById("budget-calculate");
    if (!button) {
      return;
    }
    var errorNode = document.getElementById("budget-error");
    var inputIds = [
      ["budget-income", "每月可支配金额"],
      ["budget-essential", "必要支出"],
      ["budget-flexible", "计划灵活支出"],
      ["budget-savings", "计划储蓄或缓冲"]
    ];

    function calculate() {
      clearError(errorNode);
      var values = {};
      for (var index = 0; index < inputIds.length; index += 1) {
        var id = inputIds[index][0];
        var label = inputIds[index][1];
        var value = readNumber(id);
        if (!Number.isFinite(value)) {
          showError(errorNode, "请填写“" + label + "”；若金额为 0，请明确输入 0。");
          return;
        }
        if (value < 0) {
          showError(errorNode, "“" + label + "”不能为负数。");
          return;
        }
        values[id] = value;
      }

      var income = values["budget-income"];
      if (income <= 0) {
        showError(errorNode, "每月可支配金额需大于 0，才能计算各项占比。");
        return;
      }

      var essential = values["budget-essential"];
      var flexible = values["budget-flexible"];
      var savings = values["budget-savings"];
      var allocated = essential + flexible + savings;
      var remaining = round2(income - allocated);
      var essentialPct = (essential / income) * 100;
      var flexiblePct = (flexible / income) * 100;
      var savingsPct = (savings / income) * 100;
      var openPct = (remaining / income) * 100;

      var remainingNode = document.getElementById("budget-remaining");
      if (remainingNode) {
        remainingNode.textContent =
          (remaining < 0 ? "-" : "") + formatMoney(Math.abs(remaining)) + " 元";
        remainingNode.classList.toggle("is-negative", remaining < 0);
      }

      setText(
        "budget-essential-value",
        formatMoney(essential) + " 元 · " + formatPercent(essentialPct)
      );
      setText(
        "budget-flexible-value",
        formatMoney(flexible) + " 元 · " + formatPercent(flexiblePct)
      );
      setText(
        "budget-savings-value",
        formatMoney(savings) + " 元 · " + formatPercent(savingsPct)
      );
      setText(
        "budget-open-value",
        (remaining < 0 ? "-" : "") +
          formatMoney(Math.abs(remaining)) +
          " 元 · " +
          formatPercent(openPct)
      );

      setBar("budget-essential-bar", essentialPct, formatPercent(essentialPct));
      setBar("budget-flexible-bar", flexiblePct, formatPercent(flexiblePct));
      setBar("budget-savings-bar", savingsPct, formatPercent(savingsPct));
      setBar("budget-open-bar", openPct, formatPercent(openPct));

      var summary = document.getElementById("budget-summary");
      if (summary) {
        if (remaining > 0) {
          summary.textContent =
            "还有 " +
            formatMoney(remaining) +
            " 元未分配，约为每天 " +
            formatMoney(remaining / 30) +
            " 元（按 30 天）。";
        } else if (remaining === 0) {
          summary.textContent = "各项正好用完本月可支配金额，没有未分配余额。";
        } else {
          summary.textContent =
            "计划支出超过可支配金额 " +
            formatMoney(Math.abs(remaining)) +
            " 元，需要减少支出或另找来源。";
        }
      }

      learning.markToolUsed("budget");
    }

    button.addEventListener("click", calculate);
    inputIds.forEach(function (item) {
      var input = document.getElementById(item[0]);
      if (!input) {
        return;
      }
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          calculate();
        }
      });
    });
  }

  function initScamPractice() {
    var scenarios = document.querySelectorAll("[data-scam]");
    if (!scenarios.length) {
      return;
    }

    scenarios.forEach(function (scenario) {
      scenario.querySelectorAll(".scam-option").forEach(function (button) {
        button.addEventListener("click", function () {
          if (scenario.getAttribute("data-answered") === "true") {
            return;
          }
          var isCorrect = button.getAttribute("data-correct") === "true";

          scenario.querySelectorAll(".scam-option").forEach(function (option) {
            option.disabled = true;
            if (option.getAttribute("data-correct") === "true") {
              option.classList.add("is-correct");
            }
          });
          if (!isCorrect) {
            button.classList.add("is-wrong");
          }

          var feedback = scenario.querySelector(".scam-feedback");
          var good = scenario.querySelector(".feedback-good");
          var bad = scenario.querySelector(".feedback-bad");
          if (feedback) {
            feedback.hidden = false;
          }
          if (good) {
            good.hidden = !isCorrect;
          }
          if (bad) {
            bad.hidden = isCorrect;
          }
          scenario.setAttribute("data-answered", "true");
          learning.markToolUsed("anti-fraud");

          // Move focus to the revealed explanation for keyboard users.
          if (feedback && typeof feedback.focus === "function") {
            feedback.setAttribute("tabindex", "-1");
            feedback.focus({ preventScroll: true });
          }
        });
      });
    });
  }

  initLoanCalculator();
  initBudgetTool();
  initScamPractice();
})();
