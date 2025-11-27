CREATE DATABASE  IF NOT EXISTS `owlscan`;
USE `owlscan`;

DROP TABLE IF EXISTS `images`;
CREATE TABLE `images` (
  `id` int NOT NULL AUTO_INCREMENT,
  `scan_id` int NOT NULL,
  `page_url` varchar(2083) NOT NULL,
  `image_url` varchar(2083) NOT NULL,
  `alt_text` text,
  `file_size_kb` int DEFAULT NULL,
  `is_large` tinyint(1) DEFAULT NULL,
  `missing_alt` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `scan_id` (`scan_id`),
  CONSTRAINT `images_ibfk_1` FOREIGN KEY (`scan_id`) REFERENCES `scans` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1199 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP TABLE IF EXISTS `links`;
CREATE TABLE `links` (
  `id` int NOT NULL AUTO_INCREMENT,
  `scan_id` int NOT NULL,
  `source_url` varchar(2083) NOT NULL,
  `target_url` varchar(2083) NOT NULL,
  `anchor_text` text,
  `status_code` int DEFAULT NULL,
  `is_broken` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `scan_id` (`scan_id`),
  CONSTRAINT `links_ibfk_1` FOREIGN KEY (`scan_id`) REFERENCES `scans` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2690 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP TABLE IF EXISTS `pages`;
CREATE TABLE `pages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `scan_id` int NOT NULL,
  `url` varchar(2083) NOT NULL,
  `status_code` int DEFAULT NULL,
  `title` text,
  `meta_description` text,
  `content_hash` varchar(64) DEFAULT NULL,
  `is_orphan` tinyint(1) DEFAULT NULL,
  `incoming_links` int DEFAULT NULL,
  `crawl_status` enum('new','updated','existing') DEFAULT NULL,
  `html_content` longtext,
  `word_count` int DEFAULT NULL,
  `reading_time_min` float DEFAULT NULL,
  `flesch_score` float DEFAULT NULL,
  `h1_count` int DEFAULT NULL,
  `internal_links_count` int DEFAULT NULL,
  `external_links_count` int DEFAULT NULL,
  `top_keywords` text,
  `spelling_issues_count` int DEFAULT NULL,
  `grammar_issues_count` int DEFAULT NULL,
  `spelling_examples` text,
  `grammar_error_context` text,
  PRIMARY KEY (`id`),
  KEY `scan_id` (`scan_id`),
  CONSTRAINT `pages_ibfk_1` FOREIGN KEY (`scan_id`) REFERENCES `scans` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=336 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP TABLE IF EXISTS `scans`;
CREATE TABLE `scans` (
  `id` int NOT NULL AUTO_INCREMENT,
  `start_url` varchar(2083) NOT NULL,
  `status` enum('pending','crawling','crawled','analyzing','completed','failed') NOT NULL,
  `created_at` timestamp NULL DEFAULT (now()),
  `total_issues` int DEFAULT NULL,
  `new_urls_count` int DEFAULT NULL,
  `updated_urls_count` int DEFAULT NULL,
  `existing_urls_count` int DEFAULT NULL,
  `analysis_json` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP TABLE IF EXISTS `settings`;
CREATE TABLE `settings` (
  `setting_key` varchar(50) NOT NULL,
  `setting_value` varchar(255) NOT NULL,
  PRIMARY KEY (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
