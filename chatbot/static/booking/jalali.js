/**
 * تبدیل تاریخ شمسی ↔ میلادی — الگوریتم استاندارد jalaali.
 *
 * این فایل عمداً نسخه‌ی جاوااسکریپت ساده‌ی `saghar-crm/lib/jalali.ts` است.
 * هر تغییری در یکی باید در دیگری هم اعمال شود — تقویم پنل CRM و تقویم این
 * صفحه باید همیشه یک نتیجه بدهند.
 *
 * قرارداد: هرچه به API می‌رود میلادی ISO (YYYY-MM-DD) است. شمسی فقط نمایش.
 */
(function (global) {
  "use strict";

  var BREAKS = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
    1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178
  ];

  function div(a, b) { return Math.trunc(a / b); }
  function mod(a, b) { return a - Math.trunc(a / b) * b; }

  function jalCal(jy) {
    var bl = BREAKS.length;
    var gy = jy + 621;
    var leapJ = -14;
    var jp = BREAKS[0];
    var jump = 0;
    var i, jm, n, leap, leapG, march;

    if (jy < jp || jy >= BREAKS[bl - 1]) {
      throw new Error("سال شمسی نامعتبر: " + jy);
    }

    for (i = 1; i < bl; i += 1) {
      jm = BREAKS[i];
      jump = jm - jp;
      if (jy < jm) break;
      leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
      jp = jm;
    }

    n = jy - jp;
    leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
    if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;

    leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
    march = 20 + leapJ - leapG;

    if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
    leap = mod(mod(n + 1, 33) - 1, 4);
    if (leap === -1) leap = 4;

    return { leap: leap, gy: gy, march: march };
  }

  function g2d(gy, gm, gd) {
    var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
            div(153 * mod(gm + 9, 12) + 2, 5) +
            gd - 34840408;
    d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
    return d;
  }

  function d2g(jdn) {
    var j = 4 * jdn + 139361631;
    j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
    var i = div(mod(j, 1461), 4) * 5 + 308;
    var gd = div(mod(i, 153), 5) + 1;
    var gm = mod(div(i, 153), 12) + 1;
    var gy = div(j, 1461) - 100100 + div(8 - gm, 6);
    return { gy: gy, gm: gm, gd: gd };
  }

  function j2d(jy, jm, jd) {
    var r = jalCal(jy);
    return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
  }

  function d2j(jdn) {
    var gy = d2g(jdn).gy;
    var jy = gy - 621;
    var r = jalCal(jy);
    var jdn1f = g2d(r.gy, 3, r.march);
    var k = jdn - jdn1f;

    if (k >= 0) {
      if (k <= 185) {
        return { jy: jy, jm: 1 + div(k, 31), jd: mod(k, 31) + 1 };
      }
      k -= 186;
    } else {
      jy -= 1;
      k += 179;
      if (r.leap === 1) k += 1;
    }

    return { jy: jy, jm: 7 + div(k, 30), jd: mod(k, 30) + 1 };
  }

  function toJalali(gy, gm, gd) { return d2j(g2d(gy, gm, gd)); }
  function toGregorian(jy, jm, jd) { return d2g(j2d(jy, jm, jd)); }

  function isLeapJalaliYear(jy) { return jalCal(jy).leap === 0; }

  function jalaliMonthLength(jy, jm) {
    if (jm <= 6) return 31;
    if (jm <= 11) return 30;
    return isLeapJalaliYear(jy) ? 30 : 29;
  }

  var JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
  ];

  var WEEKDAY_LABELS_FA = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"];
  var WEEKDAY_SHORT_FA = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

  function pad2(n) { return String(n).padStart(2, "0"); }

  /** Date → "YYYY-MM-DD" با اجزای محلی (نه UTC — جلوی off-by-one را می‌گیرد) */
  function dateToIso(d) {
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }

  function isoToDate(iso) {
    var p = iso.split("-").map(Number);
    return new Date(p[0], p[1] - 1, p[2]);
  }

  function jalaliToIso(jy, jm, jd) {
    var g = toGregorian(jy, jm, jd);
    return g.gy + "-" + pad2(g.gm) + "-" + pad2(g.gd);
  }

  function isoToJalaliString(iso) {
    var p = iso.split("-").map(Number);
    var j = toJalali(p[0], p[1], p[2]);
    return j.jy + "/" + pad2(j.jm) + "/" + pad2(j.jd);
  }

  function isoToJalaliLong(iso) {
    var p = iso.split("-").map(Number);
    var j = toJalali(p[0], p[1], p[2]);
    return j.jd + " " + JALALI_MONTHS[j.jm - 1] + " " + j.jy;
  }

  /**
   * ستون هفته برای چیدمان شنبه‌محور.
   * getDay(): 0=یکشنبه … 6=شنبه → ستون: شنبه=0، یکشنبه=1، … جمعه=6
   */
  function saturdayFirstColumn(d) {
    return (d.getDay() + 1) % 7;
  }

  function faDigits(v) {
    return String(v).replace(/\d/g, function (c) { return "۰۱۲۳۴۵۶۷۸۹"[Number(c)]; });
  }

  global.Jalali = {
    toJalali: toJalali,
    toGregorian: toGregorian,
    isLeapJalaliYear: isLeapJalaliYear,
    jalaliMonthLength: jalaliMonthLength,
    JALALI_MONTHS: JALALI_MONTHS,
    WEEKDAY_LABELS_FA: WEEKDAY_LABELS_FA,
    WEEKDAY_SHORT_FA: WEEKDAY_SHORT_FA,
    dateToIso: dateToIso,
    isoToDate: isoToDate,
    jalaliToIso: jalaliToIso,
    isoToJalaliString: isoToJalaliString,
    isoToJalaliLong: isoToJalaliLong,
    saturdayFirstColumn: saturdayFirstColumn,
    faDigits: faDigits
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
