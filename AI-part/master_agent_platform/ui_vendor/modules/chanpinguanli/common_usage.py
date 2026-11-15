import pymysql

def get_mysql_connection_product():
    return pymysql.connect(database="产品需求库", cursorclass=pymysql.cursors.DictCursor)

def get_mysql_connection_project():
    return pymysql.connect(database="项目需求库", cursorclass=pymysql.cursors.DictCursor)
