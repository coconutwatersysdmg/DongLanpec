/*
 Navicat Premium Dump SQL

 Source Server         : LanBin
 Source Server Type    : MySQL
 Source Server Version : 80042 (8.0.42)
 Source Host           : localhost:3306
 Source Schema         : 元件库

 Target Server Type    : MySQL
 Target Server Version : 80042 (8.0.42)
 File Encoding         : 65001

 Date: 20/11/2025 17:12:40
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for 公称压力类型标准对应表
-- ----------------------------
DROP TABLE IF EXISTS `公称压力类型标准对应表`;
CREATE TABLE `公称压力类型标准对应表`  (
  `对应ID` int NOT NULL AUTO_INCREMENT,
  `公称压力类型` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `法兰标准` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  PRIMARY KEY (`对应ID`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 14 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Records of 公称压力类型标准对应表
-- ----------------------------
INSERT INTO `公称压力类型标准对应表` VALUES (1, 'Class', 'HG/T 20615-2009');
INSERT INTO `公称压力类型标准对应表` VALUES (2, 'Class', 'HG/T 20623-2009(A)');
INSERT INTO `公称压力类型标准对应表` VALUES (3, 'Class', 'HG/T 20623-2009(B)');
INSERT INTO `公称压力类型标准对应表` VALUES (4, 'PN', 'HG/T 20592-2009');

SET FOREIGN_KEY_CHECKS = 1;
