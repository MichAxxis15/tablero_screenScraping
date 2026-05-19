import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error
import os

load_dotenv()

def initialize_database():
    try:
        connexion = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            auth_plugin='mysql_native_password'
        )

        if connexion.is_connected():
            cursor = connexion.cursor()

            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            print(f"Tablas de la base de datos: {tables}")

            if len(tables) == 0:
                print("La base de datos está vacía. Levantando modelo e insertando datos iniciales...")

                sql_ddl = r"""
                SET FOREIGN_KEY_CHECKS=0;

                DROP TABLE IF EXISTS `articulos`;
                CREATE TABLE `articulos` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `familia_id` int NOT NULL,
                  `numero_articulo` int NOT NULL,
                  `descripcion` text,
                  `ultimo_mov` date DEFAULT NULL,
                  `unidad_medida_id` int NOT NULL,
                  `costo_unitario` decimal(10,2) DEFAULT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  `contenido` decimal(10,4) DEFAULT NULL,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `numero_articulo` (`numero_articulo`),
                  KEY `familia_id` (`familia_id`),
                  KEY `unidad_medida_id` (`unidad_medida_id`),
                  CONSTRAINT `articulos_ibfk_1` FOREIGN KEY (`familia_id`) REFERENCES `familias` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
                  CONSTRAINT `articulos_ibfk_2` FOREIGN KEY (`unidad_medida_id`) REFERENCES `unidades_medida` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `categorias_producto`;
                CREATE TABLE `categorias_producto` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(100) NOT NULL,
                  `parent_id` int DEFAULT NULL,
                  `status` tinyint DEFAULT '1',
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`,`parent_id`),
                  KEY `parent_id` (`parent_id`),
                  CONSTRAINT `categorias_producto_ibfk_1` FOREIGN KEY (`parent_id`) REFERENCES `categorias_producto` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `descuentos`;
                CREATE TABLE `descuentos` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(150) NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  `punto_venta_id` int NOT NULL,
                  `tipo_producto_id` int NOT NULL,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`),
                  KEY `fk_descuento_pv` (`punto_venta_id`),
                  KEY `fk_descuento_tp` (`tipo_producto_id`),
                  CONSTRAINT `fk_descuento_pv` FOREIGN KEY (`punto_venta_id`) REFERENCES `puntos_venta` (`id`),
                  CONSTRAINT `fk_descuento_tp` FOREIGN KEY (`tipo_producto_id`) REFERENCES `tipos_producto` (`id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `familias`;
                CREATE TABLE `familias` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(100) NOT NULL,
                  `linea_id` int NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`,`linea_id`),
                  KEY `linea_id` (`linea_id`),
                  CONSTRAINT `familias_ibfk_1` FOREIGN KEY (`linea_id`) REFERENCES `lineas` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `lineas`;
                CREATE TABLE `lineas` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(100) NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `platillo_componentes`;
                CREATE TABLE `platillo_componentes` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `platillo_id` int NOT NULL,
                  `articulo_id` int DEFAULT NULL,
                  `subreceta_id` int DEFAULT NULL,
                  `cantidad` decimal(10,3) NOT NULL,
                  `costo_parcial` decimal(10,2) DEFAULT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `platillo_id` (`platillo_id`,`articulo_id`,`subreceta_id`),
                  KEY `articulo_id` (`articulo_id`),
                  KEY `subreceta_id` (`subreceta_id`),
                  CONSTRAINT `platillo_componentes_ibfk_1` FOREIGN KEY (`platillo_id`) REFERENCES `platillos` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
                  CONSTRAINT `platillo_componentes_ibfk_2` FOREIGN KEY (`articulo_id`) REFERENCES `articulos` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
                  CONSTRAINT `platillo_componentes_ibfk_3` FOREIGN KEY (`subreceta_id`) REFERENCES `subrecetas` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `platillos`;
                CREATE TABLE `platillos` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(150) NOT NULL,
                  `categoria_id` int NOT NULL,
                  `costo_manual` decimal(10,2) DEFAULT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`),
                  KEY `categoria_id` (`categoria_id`),
                  CONSTRAINT `platillos_ibfk_1` FOREIGN KEY (`categoria_id`) REFERENCES `categorias_producto` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `puntos_venta`;
                CREATE TABLE `puntos_venta` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(100) NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `subreceta_componentes`;
                CREATE TABLE `subreceta_componentes` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `subreceta_padre_id` int NOT NULL,
                  `articulo_id` int DEFAULT NULL,
                  `subreceta_id` int DEFAULT NULL,
                  `cantidad` decimal(10,3) NOT NULL,
                  `costo_parcial` decimal(10,2) DEFAULT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `subreceta_padre_id` (`subreceta_padre_id`,`articulo_id`,`subreceta_id`),
                  KEY `articulo_id` (`articulo_id`),
                  KEY `subreceta_id` (`subreceta_id`),
                  CONSTRAINT `subreceta_componentes_ibfk_1` FOREIGN KEY (`subreceta_padre_id`) REFERENCES `subrecetas` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
                  CONSTRAINT `subreceta_componentes_ibfk_2` FOREIGN KEY (`articulo_id`) REFERENCES `articulos` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
                  CONSTRAINT `subreceta_componentes_ibfk_3` FOREIGN KEY (`subreceta_id`) REFERENCES `subrecetas` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `subrecetas`;
                CREATE TABLE `subrecetas` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(150) NOT NULL,
                  `rendimiento` decimal(10,2) DEFAULT NULL,
                  `unidad_medida_id` int NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`),
                  KEY `unidad_medida_id` (`unidad_medida_id`),
                  CONSTRAINT `subrecetas_ibfk_1` FOREIGN KEY (`unidad_medida_id`) REFERENCES `unidades_medida` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `tipos_producto`;
                CREATE TABLE `tipos_producto` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(100) NOT NULL,
                  `status` tinyint(1) DEFAULT '1',
                  `punto_venta_id` INT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `nombre` (`nombre`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `turnos`;
                CREATE TABLE `turnos` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `nombre` varchar(50) NOT NULL,
                  `hora_inicio` time NOT NULL,
                  `hora_fin` time NOT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `unidades_medida`;
                CREATE TABLE `unidades_medida` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `clave` varchar(10) NOT NULL,
                  `nombre` varchar(50) NOT NULL,
                  `factor_base` decimal(10,4) DEFAULT '1.0000',
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `clave` (`clave`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `ventas`;
                CREATE TABLE `ventas` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `punto_venta_id` int NOT NULL,
                  `turno_id` int DEFAULT NULL,
                  `periodo_inicio` datetime NOT NULL,
                  `periodo_fin` datetime NOT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  `costo_total` decimal(12,2) DEFAULT '0.00',
                  `utilidad` decimal(12,2) DEFAULT '0.00',
                  `margen` decimal(10,4) DEFAULT '0.0000',
                  `total` decimal(12,2) DEFAULT '0.00',
                  `descuento` decimal(12,2) DEFAULT '0.00',
                  `subtotal` decimal(12,2) DEFAULT '0.00',
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `uniq_venta` (`punto_venta_id`,`turno_id`,`periodo_inicio`,`periodo_fin`),
                  KEY `punto_venta_id` (`punto_venta_id`),
                  KEY `turno_id` (`turno_id`),
                  KEY `periodo_inicio` (`periodo_inicio`,`periodo_fin`),
                  CONSTRAINT `ventas_ibfk_1` FOREIGN KEY (`punto_venta_id`) REFERENCES `puntos_venta` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
                  CONSTRAINT `ventas_ibfk_2` FOREIGN KEY (`turno_id`) REFERENCES `turnos` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `ventas_descuentos`;
                CREATE TABLE `ventas_descuentos` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `venta_id` int NOT NULL,
                  `descuento_id` int NOT NULL,
                  `monto` decimal(12,2) NOT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  KEY `venta_id` (`venta_id`),
                  KEY `descuento_id` (`descuento_id`),
                  CONSTRAINT `fk_vd_descuento` FOREIGN KEY (`descuento_id`) REFERENCES `descuentos` (`id`) ON DELETE RESTRICT,
                  CONSTRAINT `fk_vd_venta` FOREIGN KEY (`venta_id`) REFERENCES `ventas` (`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `ventas_no_encontrados`;
                CREATE TABLE `ventas_no_encontrados` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `venta_id` int NOT NULL,
                  `producto_nombre` varchar(255) NOT NULL,
                  `tipo_producto_id` int DEFAULT NULL,
                  `cantidad` decimal(10,2) DEFAULT NULL,
                  `total` decimal(10,2) DEFAULT NULL,
                  `costo_total` decimal(10,2) DEFAULT NULL,
                  `utilidad` decimal(10,2) DEFAULT NULL,
                  `margen` decimal(6,2) DEFAULT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  KEY `venta_id` (`venta_id`),
                  KEY `tipo_producto_id` (`tipo_producto_id`),
                  CONSTRAINT `fk_no_encontrados_tipo` FOREIGN KEY (`tipo_producto_id`) REFERENCES `tipos_producto` (`id`) ON DELETE SET NULL,
                  CONSTRAINT `fk_no_encontrados_venta` FOREIGN KEY (`venta_id`) REFERENCES `ventas` (`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                DROP TABLE IF EXISTS `ventas_platillo`;
                CREATE TABLE `ventas_platillo` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `venta_id` int NOT NULL,
                  `platillo_id` int NOT NULL,
                  `tipo_producto_id` int NOT NULL,
                  `cantidad` int NOT NULL,
                  `total` decimal(10,2) NOT NULL,
                  `costo_total` decimal(10,2) DEFAULT NULL,
                  `utilidad` decimal(10,2) DEFAULT '0.00',
                  `margen` decimal(10,4) DEFAULT NULL,
                  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
                  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `venta_id` (`venta_id`,`platillo_id`,`tipo_producto_id`),
                  KEY `venta_id_2` (`venta_id`),
                  KEY `platillo_id` (`platillo_id`),
                  KEY `tipo_producto_id` (`tipo_producto_id`),
                  CONSTRAINT `ventas_platillo_ibfk_1` FOREIGN KEY (`venta_id`) REFERENCES `ventas` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
                  CONSTRAINT `ventas_platillo_ibfk_2` FOREIGN KEY (`platillo_id`) REFERENCES `platillos` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
                  CONSTRAINT `ventas_platillo_ibfk_3` FOREIGN KEY (`tipo_producto_id`) REFERENCES `tipos_producto` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
                """

                sql_dml = r"""
                LOCK TABLES `puntos_venta` WRITE;
                /*!40000 ALTER TABLE `puntos_venta` DISABLE KEYS */;
                INSERT INTO `puntos_venta` VALUES (1,'Mulligan NC',1,'2026-04-23 12:15:13','2026-04-23 17:45:54'), (2,'Restaurante Vista del Lago',1,'2026-04-23 12:15:13','2026-04-23 18:17:28'), (3,'Sushi',1,'2026-04-23 12:15:13','2026-04-23 12:15:13'), (4,'Callos de cortes',1,'2026-04-23 12:15:13','2026-04-23 17:45:54'), (5,'Hoyo 10',1,'2026-04-23 12:15:13','2026-04-23 17:45:54'), (6,'Carrito 1',1,'2026-04-23 12:15:13','2026-04-23 12:15:13'), (7,'Carrito 2',1,'2026-04-23 12:15:13','2026-04-23 12:15:13');
                /*!40000 ALTER TABLE `puntos_venta` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `lineas` WRITE;
                /*!40000 ALTER TABLE `lineas` DISABLE KEYS */;
                INSERT INTO `lineas` VALUES 
                    (1,'AYB',1),
                    (2,'CAMPO DE GOLF',1),
                    (3,'CASA CLUB',1),
                    (4,'MANTENIMIENTO',1),
                    (5,'MATERIALES',1),
                    (6,'NAVE DE CARRITOS',1),
                    (7,'PERFORMANCE LAB',1),
                    (8,'SERVICIOS',1),
                    (9,'SUMINISTROS GENERALES',1);
                /*!40000 ALTER TABLE `lineas` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `familias` WRITE;
                /*!40000 ALTER TABLE `familias` DISABLE KEYS */;
                INSERT INTO `familias` VALUES 
                    (1,'ABARROTES',1,1),
                    (2,'AVES',1,1),
                    (3,'BEBIDAS ALCOHOLICAS',1,1),
                    (4,'BEBIDAS NO ALCOHOLICAS',1,1),
                    (5,'CARNES',1,1),
                    (6,'CONGELADOS',1,1),
                    (7,'DULCES Y PALETAS',1,1),
                    (8,'EMBUTIDOS Y CARNES FRÍAS',1,1),
                    (9,'FRUTAS Y VERDURAS',1,1),
                    (10,'LACTEOS',1,1),
                    (11,'PESCADOS Y MARISCOS',1,1),
                    (12,'TABACO',1,1),
                    (13,'VINOS DE MESA',1,1),
                    (14,'AGROQUIMICOS',2,1),
                    (15,'ARTÍCULOS DE GOLF',2,1),
                    (16,'COMBUSTIBLES',2,1),
                    (17,'EQUIPO / HERRAMIENTA / HERRAMIENTA MENOR',2,1),
                    (18,'INSUMOS',2,1),
                    (19,'MATERIALES',2,1),
                    (20,'NAVE DE CARRITOS',2,1),
                    (21,'REFACCIONES',2,1),
                    (22,'SERVICIOS',2,1),
                    (23,'ARTÍCULOS DEPORTIVOS',3,1),
                    (24,'ARTÍCULOS MÉDICOS',3,1),
                    (25,'EQUIPO DE GIMNASIO',3,1),
                    (26,'EVENTOS',3,1),
                    (27,'ALBERCA',4,1),
                    (28,'EQUIPO',4,1),
                    (29,'HERRAMIENTA',4,1),
                    (30,'MATERIAL ELÉCTRICO',4,1),
                    (31,'PINTURA',4,1),
                    (32,'PLOMERIA',4,1),
                    (33,'REFACCIONES',4,1),
                    (34,'SERVICIOS',4,1),
                    (35,'AGROQUIMICOS',5,1),
                    (36,'COMBUSTIBLE',5,1),
                    (37,'FERTILIZANTES Y SEMILLAS',5,1),
                    (38,'MANTENIMIENTO EQUIPO RIEGO',5,1),
                    (39,'REFACCIONES MAQUINARIA Y EQUIPO MENOR',5,1),
                    (40,'ACCESORIOS',6,1),
                    (41,'BATERÍAS',6,1),
                    (42,'CONSUMIBLES',6,1),
                    (43,'HERRAMIENTA',6,1),
                    (44,'REFACCIONES',6,1),
                    (45,'ACCESORIOS DE GOLF',7,1),
                    (46,'CABEZAS / BASTONES',7,1),
                    (47,'COMPONENTES DE ENSAMBLE',7,1),
                    (48,'EQUIPO DE TALLER',7,1),
                    (49,'GRIPS',7,1),
                    (50,'HERRAMIENTAS DE TALLER',7,1),
                    (51,'VARILLAS',7,1),
                    (52,'ARRENDAMIENTO',8,1),
                    (53,'LAVANDERÍA',8,1),
                    (54,'SERVICIOS',8,1),
                    (55,'ARTÍCULOS DE VENTA',9,1),
                    (56,'CONSUMIBLES',9,1),
                    (57,'EQUIPAMIENTO CASA CLUB',9,1),
                    (58,'EQUIPO RESTAURANT',9,1),
                    (59,'PAPELERÍA',9,1),
                    (60,'SOFTWARE',9,1),
                    (61,'SUMINISTROS DE LIMPIEZA',9,1),
                    (62,'SUMINISTROS DE SISTEMAS',9,1),
                    (63,'SUMINISTROS DESECHABLES',9,1),
                    (64,'SUMINISTROS QUÍMICOS',9,1);
                /*!40000 ALTER TABLE `familias` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `descuentos` WRITE;
                /*!40000 ALTER TABLE `descuentos` DISABLE KEYS */;
                INSERT INTO `descuentos` VALUES 
                    (1,'Descuento Mulligan',1,1,23),
                    (2,'Descuento Vista lago',1,2,23),
                    (3,'Descuento Sushi',1,3,23),
                    (4,'Descuento Callos',1,4,23),
                    (5,'Descuento Hoyo 10',1,5,23),
                    (6,'Descuento Carrito 1',1,6,23),
                    (7,'Descuento Carrito 2',1,7,23),
                    (8,'Descuento CS',1,4,23),
                    (9,'Descuento SU',1,3,23);
                /*!40000 ALTER TABLE `descuentos` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `categorias_producto` WRITE;
                /*!40000 ALTER TABLE `categorias_producto` DISABLE KEYS */;
                INSERT INTO `categorias_producto` VALUES 
                    (1,'BARRA',NULL,1),
                    (2,'Cafés',1,1),
                    (3,'Te\'s',1,1),
                    (4,'Bebidas Frías',1,1),
                    (5,'Cockteles',1,1),
                    (6,'Cervezas',1,1),
                    (7,'Jugos',1,1),
                    (8,'Vinos',1,1),
                    (9,'Licores',1,1),
                    (10,'Mezcladores Barra',1,1),
                    (11,'Sub recetas jugos',7,1),
                    (12,'Los especiales',7,1),
                    (13,'Tintos',8,1),
                    (14,'Blancos/Rosados/Espumosos',8,1),
                    (15,'Brandy & Cognac',9,1),
                    (16,'Aperitivos',9,1),
                    (17,'Ginebra y Vodka',9,1),
                    (18,'Mezcal',9,1),
                    (19,'Ron',9,1),
                    (20,'Tequila',9,1),
                    (21,'Whisky',9,1),
                    (22,'DESAYUNOS',NULL,1),
                    (23,'Chilaquiles',22,1),
                    (24,'Clásicos',22,1),
                    (25,'Especialidades',22,1),
                    (26,'De la Granja',22,1),
                    (27,'Fruta',22,1),
                    (28,'Cereales y Panes',22,1),
                    (29,'Buffete Desayuno',22,1),
                    (30,'Huevos',26,1),
                    (31,'COMIDAS/CENAS',NULL,1),
                    (32,'Antojitos Mexicanos',31,1),
                    (33,'Entradas',31,1),
                    (34,'Sopas',31,1),
                    (35,'Pastas',31,1),
                    (36,'Menús Especiales',31,1),
                    (37,'Aves',31,1),
                    (38,'Mariscos',31,1),
                    (39,'Carnes Rojas',31,1),
                    (40,'Clasicos',31,1),
                    (41,'Enchiladas',31,1),
                    (42,'Buffet Comida/Cena',31,1),
                    (43,'Burritos/Chapatas/Sandwiches',31,1),
                    (44,'Hamburguesas/HotDogs',31,1),
                    (45,'Parrillada',31,1),
                    (46,'Ensaladas',31,1),
                    (47,'Botanas',31,1),
                    (48,'Menú Infantil',31,1),
                    (49,'SUB RECETAS',NULL,1),
                    (50,'Platillos',49,1),
                    (51,'Pastelería',49,1),
                    (52,'EXTRAS',NULL,1),
                    (53,'Con costo',52,1),
                    (54,'Sin costo',52,1),
                    (55,'Modificadores',52,1),
                    (56,'GUARNICIONES',NULL,1),
                    (57,'POSTRES',NULL,1),
                    (58,'TABACO',NULL,1),
                    (59,'SUSHI',NULL,1),
                    (60,'CALLOS CORTES',NULL,1),
                    (61,'SNACK',NULL,1),
                    (62,'Dulces',57,1),
                    (63,'Entradas',59,1),
                    (64,'Tostadas',59,1),
                    (65,'Yakimeshi',59,1),
                    (66,'Bowls',59,1),
                    (67,'Rollos tradicionales',59,1),
                    (68,'Rollos especiales',59,1),
                    (69,'Rollos empanizados',59,1),
                    (70,'Postres',59,1),
                    (71,'Extras',59,1),
                    (72,'Ramen y pastas',59,1),
                    (73,'Especialidades',59,1),
                    (74,'Subrecetas Salsas',59,1),
                    (75,'Guarniciones Sushi',59,1),
                    (76,'Ensaladas',59,1),
                    (77,'Cócteles',59,1),
                    (78,'Sashimi',59,1),
                    (79,'Sub recetas callos',60,1),
                    (80,'Marisquería',60,1),
                    (81,'A elegir',80,1),
                    (82,'Ceviches',80,1),
                    (83,'Tacos',80,1),
                    (84,'Tostadas',80,1),
                    (85,'Mariscadas',80,1);
                /*!40000 ALTER TABLE `categorias_producto` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `turnos` WRITE;
                /*!40000 ALTER TABLE `turnos` DISABLE KEYS */;
                INSERT INTO `turnos` VALUES 
	                (1,'Mañana','07:00:00','13:59:00','2026-04-23 12:15:22','2026-04-23 17:13:22'),
                    (2,'Tarde/Noche','14:00:00','03:00:00','2026-04-23 12:15:22','2026-04-23 17:14:19');
                /*!40000 ALTER TABLE `turnos` ENABLE KEYS */;

                LOCK TABLES `tipos_producto` WRITE;
                /*!40000 ALTER TABLE `tipos_producto` DISABLE KEYS */;
                INSERT INTO `tipos_producto` VALUES 
                    (1,'Vista Alimentos',1,2,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (2,'Vista Bebidas con alcohol',1,2,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (3,'Vista Bebidas sin alcohol',1,2,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (4,'Mulligan Alimentos',1,1,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (5,'Mulligan Bebidas con alcohol',1,1,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (6,'Mulligan Bebidas sin alcohol',1,1,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (7,'Sushi Alimentos',1,3,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (8,'Sushi Bebidas con alcohol',1,3,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (9,'Sushi Bebidas sin alcohol',1,3,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (10,'Callos Alimentos',1,4,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (11,'Callos Bebidas con alcohol',1,4,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (12,'Callos Bebidas sin alcohol',1,4,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (13,'Carrito 1 Alimentos',1,6,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (14,'Carrito 1 Bebidas con alcohol',1,6,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (15,'Carrito 1 Bebidas sin alcohol',1,6,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (16,'Carrito 2 Alimentos',1,7,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (17,'Carrito 2 Bebidas con alcohol',1,7,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (18,'Carrito 2 Bebidas sin alcohol',1,7,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (19,'Hoyo 10 Alimentos',1,5,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (20,'Hoyo 10 Bebidas con alcohol',1,5,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (21,'Hoyo 10 Bebidas sin alcohol',1,5,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (22,'Tabaco',1, NULL,'2026-04-23 12:15:31','2026-04-23 12:15:31'),
                    (23,'Descuentos',1, NULL,'2026-04-23 12:15:31','2026-04-23 12:15:31');
                /*!40000 ALTER TABLE `tipos_producto` ENABLE KEYS */;
                UNLOCK TABLES;

                LOCK TABLES `unidades_medida` WRITE;
                /*!40000 ALTER TABLE `unidades_medida` DISABLE KEYS */;
                INSERT INTO `unidades_medida` VALUES 
                    (1,'kg','Kilogramo',1.0000),
                    (2,'lt','Litro',1.0000),
                    (3,'ml','Mililitros',1.0000),
                    (4,'gr','Gramos',1.0000),
                    (5,'pz','Pieza',1.0000),
                    (7,'mt','Metro',1.0000),
                    (8,'srv','Servicio',1.0000);
                /*!40000 ALTER TABLE `unidades_medida` ENABLE KEYS */;
                UNLOCK TABLES;

                SET FOREIGN_KEY_CHECKS=1;
                """

                sql_completo = sql_ddl + "\n" + sql_dml
                sql_statements = sql_completo.split(';')

                for statement in sql_statements:
                    statement = statement.strip()
                    if statement:
                        cursor.execute(statement)

                connexion.commit()
                print("¡Estructura de tablas y datos iniciales creados con éxito!")
            else:
                print(f"Se omitió la creación e inserción. La base de datos ya contiene {len(tables)} tablas.")

    except Error as e:
        print(f"Error al conectar a MYSQL: {e}")
    finally:
        if 'connexion' in locals() and connexion.is_connected():
            cursor.close()
            connexion.close()

def crear_vista_resumen():
    """Crea (o reemplaza) la vista v_resumen_punto_venta en la base de datos."""
    try:
        connexion = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            auth_plugin='mysql_native_password'
        )

        if connexion.is_connected():
            cursor = connexion.cursor()

            vista_sql = """
            CREATE OR REPLACE VIEW v_resumen_punto_venta AS
            WITH Totales_Globales AS (
                SELECT
                    SUM(total) AS gran_total_ventas,
                    SUM(costo_total) AS gran_total_costos,
                    SUM(utilidad) AS gran_total_utilidad
                FROM ventas
            ),
            Detalle_Puntos_Venta AS (
                SELECT
                    pv.nombre AS punto_venta,
                    SUM(v.total) AS ventas,
                    SUM(v.costo_total) AS costos,
                    SUM(v.utilidad) AS utilidad_bruta
                FROM ventas v
                JOIN puntos_venta pv ON v.punto_venta_id = pv.id
                GROUP BY pv.nombre
            )
            SELECT
                d.punto_venta AS punto_de_venta,
                d.ventas AS ventas,
                ROUND((d.ventas / t.gran_total_ventas) * 100, 2) AS pct_ventas,
                d.costos AS costos,
                ROUND((d.costos / t.gran_total_costos) * 100, 2) AS pct_costos,
                d.utilidad_bruta AS ut_bruta,
                ROUND((d.utilidad_bruta / t.gran_total_utilidad) * 100, 2) AS pct_ut_bruta,
                ROUND((d.utilidad_bruta / d.ventas) * 100, 2) AS margen_pct
            FROM Detalle_Puntos_Venta d
            CROSS JOIN Totales_Globales t

            UNION ALL

            SELECT
                'Total',
                t.gran_total_ventas,
                100.00,
                t.gran_total_costos,
                100.00,
                t.gran_total_utilidad,
                100.00,
                ROUND((t.gran_total_utilidad / t.gran_total_ventas) * 100, 2)
            FROM Totales_Globales t
            """

            cursor.execute(vista_sql)
            connexion.commit()
            print("Vista v_resumen_punto_venta creada/actualizada con éxito.")

    except Error as e:
        print(f"Error al crear la vista: {e}")
    finally:
        if 'connexion' in locals() and connexion.is_connected():
            cursor.close()
            connexion.close()


if __name__ == '__main__':
    initialize_database()