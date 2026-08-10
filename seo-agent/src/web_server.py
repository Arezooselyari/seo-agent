"""وب‌سرور برای داشبورد تایید مقالات.

این سرور:
1. داشبوردی برای دیدن مقالات pending نمایش می‌دهد
2. API endpoints برای دریافت و به‌روزرسانی وضعیت مقالات فراهم می‌کند
3. Approve/Reject/Cancel دکمه‌ها را نمایش می‌دهد
"""

import json
import logging
from datetime import datetime

from flask import Flask, jsonify, request

from . import db

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/", methods=["GET"])
def dashboard():
    """داشبورد HTML را برمی‌گرداند."""
    return """
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>داشبورد تایید مقالات</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            h1 { color: #333; margin-bottom: 20px; text-align: center; }

            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }

            .stat-card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                text-align: center;
            }

            .stat-label { color: #666; font-size: 14px; margin-bottom: 10px; }
            .stat-value { font-size: 32px; font-weight: bold; color: #2196F3; }

            .articles-list { display: flex; flex-direction: column; gap: 15px; }

            .article-card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }

            .article-header {
                display: flex;
                justify-content: space-between;
                align-items: start;
                margin-bottom: 15px;
                gap: 15px;
            }

            .article-title { font-size: 18px; font-weight: bold; color: #333; flex: 1; }
            .article-score {
                font-size: 24px;
                font-weight: bold;
                padding: 10px 15px;
                border-radius: 6px;
                text-align: center;
            }

            .score-high { background: #c8e6c9; color: #2e7d32; }
            .score-low { background: #ffccbc; color: #d84315; }

            .article-preview {
                background: #f9f9f9;
                padding: 12px;
                border-radius: 6px;
                margin-bottom: 15px;
                color: #666;
                line-height: 1.6;
                font-size: 14px;
                max-height: 150px;
                overflow-y: auto;
            }

            .article-meta {
                display: flex;
                gap: 20px;
                font-size: 13px;
                color: #999;
                margin-bottom: 15px;
            }

            .article-actions {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }

            button {
                padding: 10px 20px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.2s;
            }

            .btn-approve {
                background: #4CAF50;
                color: white;
            }
            .btn-approve:hover { background: #45a049; }

            .btn-reject {
                background: #f44336;
                color: white;
            }
            .btn-reject:hover { background: #da190b; }

            .btn-cancel {
                background: #9E9E9E;
                color: white;
            }
            .btn-cancel:hover { background: #757575; }

            .loading { text-align: center; color: #999; padding: 40px; }
            .empty { text-align: center; color: #ccc; padding: 40px; }

            .status-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
            }

            .status-pending { background: #fff9c4; color: #f57f17; }
            .status-approved { background: #c8e6c9; color: #2e7d32; }
            .status-rejected { background: #ffccbc; color: #d84315; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 داشبورد تایید مقالات SEO</h1>

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-label">در انتظار تایید</div>
                    <div class="stat-value" id="pending-count">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">امتیاز بالا (≥90)</div>
                    <div class="stat-value" id="approved-count">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">نیاز به بررسی</div>
                    <div class="stat-value" id="review-count">-</div>
                </div>
            </div>

            <div id="articles-container" class="articles-list">
                <div class="loading">⏳ درحال بارگذاری مقالات...</div>
            </div>
        </div>

        <script>
            async function fetchArticles() {
                try {
                    const response = await fetch('/api/pending-articles');
                    const data = await response.json();
                    renderArticles(data);
                    updateStats(data);
                } catch (error) {
                    console.error('خطا در بارگذاری مقالات:', error);
                    document.getElementById('articles-container').innerHTML =
                        '<div class="empty">❌ خطا در بارگذاری مقالات</div>';
                }
            }

            function updateStats(data) {
                document.getElementById('pending-count').textContent = data.pending.length;
                document.getElementById('approved-count').textContent = data.approved.length;
                document.getElementById('review-count').textContent = data.needs_review.length;
            }

            function renderArticles(data) {
                const container = document.getElementById('articles-container');
                container.innerHTML = '';

                // Render approved articles (score >= 90)
                if (data.approved.length > 0) {
                    const section = document.createElement('div');
                    section.innerHTML = '<h2 style="margin-top: 30px; margin-bottom: 15px; color: #4CAF50;">✅ امتیاز بالا (آماده تایید)</h2>';
                    container.appendChild(section);

                    data.approved.forEach(article => {
                        container.appendChild(createArticleCard(article, 'approved'));
                    });
                }

                // Render needs_review articles (score < 90)
                if (data.needs_review.length > 0) {
                    const section = document.createElement('div');
                    section.innerHTML = '<h2 style="margin-top: 30px; margin-bottom: 15px; color: #f44336;">📌 نیاز به بررسی</h2>';
                    container.appendChild(section);

                    data.needs_review.forEach(article => {
                        container.appendChild(createArticleCard(article, 'needs_review'));
                    });
                }

                if (data.approved.length === 0 && data.needs_review.length === 0) {
                    container.innerHTML = '<div class="empty">🎉 همه مقالات مورد بررسی قرار گرفتند!</div>';
                }
            }

            function createArticleCard(article, category) {
                const card = document.createElement('div');
                card.className = 'article-card';

                const scoreClass = article.seo_grade >= 90 ? 'score-high' : 'score-low';
                const createdAt = new Date(article.created_at).toLocaleString('fa-IR');

                let actionsHTML = '';
                if (article.status === 'pending') {
                    actionsHTML = `
                        <button class="btn-approve" onclick="approveArticle(${article.article_id})">✅ تایید</button>
                        <button class="btn-reject" onclick="rejectArticle(${article.article_id})">❌ ردّ</button>
                        <button class="btn-cancel" onclick="cancelArticle(${article.article_id})">⊗ لغو</button>
                    `;
                }

                card.innerHTML = `
                    <div class="article-header">
                        <div class="article-title">${article.title}</div>
                        <div class="article-score ${scoreClass}">${article.seo_grade}</div>
                    </div>
                    <div class="article-preview">${article.preview}</div>
                    <div class="article-meta">
                        <span>📅 ${createdAt}</span>
                        <span>🆔 مقاله #${article.article_id}</span>
                        <span class="status-badge status-${article.status}">${article.status}</span>
                    </div>
                    <div class="article-actions">
                        ${actionsHTML}
                    </div>
                `;

                return card;
            }

            async function approveArticle(articleId) {
                await updateArticleStatus(articleId, 'approved');
            }

            async function rejectArticle(articleId) {
                await updateArticleStatus(articleId, 'rejected');
            }

            async function cancelArticle(articleId) {
                await updateArticleStatus(articleId, 'pending');
            }

            async function updateArticleStatus(articleId, status) {
                try {
                    const response = await fetch(`/api/articles/${articleId}/approve`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status })
                    });

                    if (response.ok) {
                        fetchArticles();  // Refresh list
                    } else {
                        alert('خطا در به‌روزرسانی وضعیت');
                    }
                } catch (error) {
                    console.error('خطا:', error);
                    alert('خطا در ارسال درخواست');
                }
            }

            // Load articles on page load
            document.addEventListener('DOMContentLoaded', fetchArticles);

            // Refresh every 30 seconds
            setInterval(fetchArticles, 30000);
        </script>
    </body>
    </html>
    """


@app.route("/api/pending-articles", methods=["GET"])
def get_pending_articles():
    """تمام pending و needs_review articles را برمی‌گرداند."""
    conn = db.connect()
    try:
        # Get evaluation results
        from . import evaluator

        results = evaluator.evaluate_pending_articles(conn, threshold=90)

        return jsonify({
            "pending": results["approved"] + results["needs_review"],
            "approved": results["approved"],
            "needs_review": results["needs_review"],
            "total": results["total"],
        })

    finally:
        conn.close()


@app.route("/api/articles/<int:article_id>/approve", methods=["POST"])
def approve_article(article_id):
    """مقاله را تایید/ردّ می‌کند."""
    data = request.json or {}
    status = data.get("status", "approved")

    if status not in ["approved", "rejected", "pending"]:
        return jsonify({"error": "وضعیت نامعتبر"}), 400

    conn = db.connect()
    try:
        article = db.get_article(conn, article_id)
        if not article:
            return jsonify({"error": "مقاله یافت نشد"}), 404

        db.set_status(conn, article_id, status)

        logger.info(f"مقاله #{article_id} به وضعیت '{status}' تغییر کرد (وب)")

        return jsonify({"success": True, "article_id": article_id, "status": status})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    app.run(debug=True, host="0.0.0.0", port=5000)
