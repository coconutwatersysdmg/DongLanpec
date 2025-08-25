import os
import sys

from PyQt5.QtWidgets import (QMainWindow, QLabel, QComboBox, QPushButton, QLineEdit,
                             QDataWidgetMapper, QTableView, QListView, QTabWidget,
                             QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QScrollArea, QMessageBox, QFileDialog, QDialog,
                             QDialogButtonBox, QApplication, QWidget, QGraphicsView,
                             QGraphicsScene, QGraphicsPixmapItem, QListWidgetItem)
from PyQt5.QtCore import Qt, QRect, QSize, QStringListModel, QModelIndex, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QPainter, QBrush, QColor, QFont, QIcon
from typing import List, Dict, Tuple, Optional
# from TubeDistributionCore import TubePlantInfo


class TubeDistributeParamData:
    def __init__(self):
        self.paramId = ""
        self.refParamId = ""
        self.paramName = ""
        self.paramValue = ""
        self.paramUnit = ""
        self.paramValueType = ""
        self.isReadOnly = ""
        self.Item = []

    def CopyData(self, other):
        self.paramId = other.paramId
        self.refParamId = other.refParamId
        self.paramName = other.paramName
        self.paramValue = other.paramValue
        self.paramUnit = other.paramUnit
        self.paramValueType = other.paramValueType
        self.isReadOnly = other.isReadOnly
        self.Item = other.Item.copy()


class ScriptItem1:
    def __init__(self):
        pass


class LayoutTubeParam:
    def __init__(self):
        self.Bn = 0.0
        self.S = 0.0
        self.SN = 0.0
        self.BaffleToODistance = 0.0
        self.SlipWayHeight = 0.0
        self.PassagewayWidth = 0
        self.BaffleOD = 0.0
        self.DL = 0.0
        self.SlipWayAngle = 0.0
        self.SlipWayThick = 0.0
        self.BPBThick = 0.0
        self.BPBHeights = []
        self.TubesParam = []
        self.AllTubesParam = []
        self.CountLines = []


class TubeBoardConnectData:
    def __init__(self):
        self.type = 0
        self.subtype = 0
        self.weldJoint = ""


class HelpCore:
    @staticmethod
    def InitHelpProvider(widget, help_provider, help_string):
        pass


class ProjectCore:
    @staticmethod
    def GetDFTPicturePath(imagePath: str):
        imagePath = ""


@staticmethod
def AskProjectPath(prjPath: str):
    prjPath = ""


class TubeDistributionGUI(QWidget):
    def __init__(self):
        super().__init__()
        print(4444)
        # self.m_mainData = TubeDistributionCore()
        self.m_listInputParam = []
        self.m_outputParam = LayoutTubeParam()
        self.m_tubeBoardData = TubeBoardConnectData()
        self.m_allTubePoints1 = {}  # 上半部分管道坐标（所有列管）
        self.m_allTubePoints2 = {}  # 下半部分管道坐标（所有列管）
        self.m_editTubeCntFlag = False

        self.setWindowTitle("布管参数设计")
        self.resize(800, 600)
        print(2222)
        self.init_ui()
        print(1111)
        self.InitDialog()
        print(333)


    def init_ui(self):
        # Main layout
        main_layout = QVBoxLayout()

        # Tab widget
        self.tabControlTube = QTabWidget()

        # Input parameters tab
        self.tabInput = QWidget()
        self.tabOutput = QWidget()

        self.tabControlTube.addTab(self.tabInput, "布管")
        self.tabControlTube.addTab(self.tabOutput, "输出参数")

        self.init_input_tab()
        self.init_output_tab()

        # Tube board connection
        self.init_tube_board_connection()

        # Buttons
        button_layout = QHBoxLayout()
        self.mOkButton = QPushButton("确定")
        self.mCancelButton = QPushButton("取消")
        self.qyButtonCalculate = QPushButton("计算")

        button_layout.addWidget(self.qyButtonCalculate)
        button_layout.addStretch()
        button_layout.addWidget(self.mOkButton)
        button_layout.addWidget(self.mCancelButton)

        main_layout.addWidget(self.tabControlTube)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # Connect signals
        self.mOkButton.clicked.connect(self.mOkButton_Click)
        self.mCancelButton.clicked.connect(self.mCancelButton_Click)
        self.qyButtonCalculate.clicked.connect(self.qyButtonCalculate_Click)

    def init_input_tab(self):
        layout = QVBoxLayout()

        # Picture box
        self.mPictureBoxTube = QGraphicsView()
        self.scene = QGraphicsScene()
        self.mPictureBoxTube.setScene(self.scene)

        # Data grid for tube parameters
        self.mDataGridViewTubeParam = QTableView()

        # Input parameter panel (hidden by default)
        self.panelInputParam = QWidget()
        self.panelInputParam.setVisible(False)
        input_param_layout = QHBoxLayout()
        self.comboBoxInputParam = QComboBox()
        input_param_layout.addWidget(self.comboBoxInputParam)
        self.panelInputParam.setLayout(input_param_layout)

        layout.addWidget(self.mPictureBoxTube)
        layout.addWidget(self.mDataGridViewTubeParam)
        layout.addWidget(self.panelInputParam)

        self.tabInput.setLayout(layout)

        # Connect signals
        self.comboBoxInputParam.currentIndexChanged.connect(self.comboBoxInputParam_SelectedIndexChanged)
        self.comboBoxInputParam.editTextChanged.connect(self.comboBoxInputParam_TextUpdate)
        self.mDataGridViewTubeParam.clicked.connect(self.mDataGridViewTubeParam_CellClick)

    def init_output_tab(self):
        layout = QVBoxLayout()

        # Output parameters
        self.mDataGridViewOutputParam = QTableView()

        # Tube count
        self.labelTubeTotalCnt = QLabel("换热管总数：0")
        self.mDataGridViewTubeCnt = QTableView()

        layout.addWidget(self.mDataGridViewOutputParam)
        layout.addWidget(self.labelTubeTotalCnt)
        layout.addWidget(self.mDataGridViewTubeCnt)

        self.tabOutput.setLayout(layout)

        # Connect signals
        self.mDataGridViewTubeCnt.clicked.connect(self.mDataGridViewTubeCnt_CellClick)
        self.mDataGridViewTubeCnt.model().dataChanged.connect(self.mDataGridViewTubeCnt_CellValueChanged)

    def init_tube_board_connection(self):
        # This would be part of the main layout or a separate tab
        pass

    def InitDialog(self):
        self.InitDialogCtrl()
        self.InitDialogData()
        return 0

    def InitDialogCtrl(self):
        imagePath = ""

        # Initialize tube distribution bitmap
        # m_mainData.AskDefaultTubeDistributeImage(out imagePath)
        if imagePath and os.path.exists(imagePath):
            pixmap = QPixmap(imagePath)
            self.scene.addPixmap(pixmap)

        self.panelInputParam.setVisible(False)
        return 0

    def InitDialogData(self):
        # Set default tab (tube layout)
        self.tabControlTube.setCurrentIndex(0)

        # Initialize input parameters
        self.InitInputParams()

        # Initialize output parameters
        self.InitOutputParams()

        # Initialize heat exchange tube and tube sheet connection types
        self.mComboBoxTubeBoard.clear()
        self.mComboBoxTubeBoard.addItems([
            "机械强度胀接加密封焊",
            "强度焊接",
            "强度胀接",
            "内孔焊"
        ])
        self.mComboBoxTubeBoard.setCurrentIndex(0)
        self.mPanelWeldJoint.setVisible(False)

        # Get initial info for heat exchange tube and tube sheet connection
        # m_mainData.AskTubeBoardInfoFromFile(out m_tubeBoardData)
        # Update heat exchange tube and tube sheet connection content
        self.mComboBoxTubeBoard.setCurrentIndex(self.m_tubeBoardData.type)
        self.UpdateTubeBoardConnectData()

        return 0

    def InitInputParams(self):
        rowIndex = 0
        paramData1 = TubeDistributeParamData()

        # Get input parameters
        self.m_listInputParam = self.m_mainData.GetInputParam()
        # m_mainData.AskInputParams(out m_listInputParam, True)

        # Initialize output parameter list
        self.mDataGridViewTubeParam.model().removeRows(0, self.mDataGridViewTubeParam.model().rowCount())

        for i in range(len(self.m_listInputParam)):
            paramData1 = self.m_listInputParam[i]
            rowIndex = self.mDataGridViewTubeParam.model().rowCount()
            self.mDataGridViewTubeParam.model().insertRow(rowIndex)

            # Serial number
            self.mDataGridViewTubeParam.model().setData(
                self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_No1), str(i + 1))

            # Parameter ID
            if paramData1.paramId:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_ParamId1),
                    paramData1.paramId)

            # Reference ID
            if paramData1.refParamId:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_RefId1),
                    paramData1.refParamId)

            # Parameter name
            if paramData1.paramName:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_ParamName1),
                    paramData1.paramName)

            # Parameter value
            if paramData1.paramValue:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_ParamValue1),
                    paramData1.paramValue)

            # Unit
            if paramData1.paramUnit:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_ParamUnit1),
                    paramData1.paramUnit)

            # Parameter value type
            if paramData1.paramValueType:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_ParamValueType1),
                    paramData1.paramValueType)

            # Is parameter value read-only
            if paramData1.isReadOnly:
                self.mDataGridViewTubeParam.model().setData(
                    self.mDataGridViewTubeParam.model().index(rowIndex, self.Col_IsReadValue1),
                    paramData1.isReadOnly)

        return 0

    def InitOutputParams(self):
        resp = -1
        imagePath = ""

        # Get output parameters from cache file
        self.m_outputParam = self.m_mainData.GetTubOutputData()
        if not self.m_outputParam:
            return resp

        # Convert output pipeline coordinate data to row and column grouped point data
        if len(self.m_outputParam.TubesParam) == 2:
            if self.m_outputParam.AllTubesParam and len(self.m_outputParam.AllTubesParam) > 0:
                pass
                # m_mainData.TransTubeParamToPoints(m_outputParam.AllTubesParam[0].ScriptItem, out m_allTubePoints1, 0)
            if self.m_outputParam.AllTubesParam and len(self.m_outputParam.AllTubesParam) > 1:
                pass
                # m_mainData.TransTubeParamToPoints(m_outputParam.AllTubesParam[1].ScriptItem, out m_allTubePoints2, 1)

        # Initialize output parameters
        self.UpdateOutputParams(self.m_outputParam)

        # Initialize row and column tube count
        self.UpdateTubeCountLines(self.m_outputParam)

        # Update total number of heat exchange tubes
        self.UpdateTubeTotalCount(self.m_outputParam)

        # Get corresponding bitmap based on calculation results
        ProjectCore.GetDFTPicturePath(imagePath)

        # Update image
        if imagePath and os.path.exists(imagePath):
            pixmap = QPixmap(imagePath)
            self.scene.addPixmap(pixmap)

        return 0

    def comboBoxInputParam_SelectedIndexChanged(self, index):
        if self.mDataGridViewTubeParam.currentIndex().isValid():
            self.mDataGridViewTubeParam.model().setData(
                self.mDataGridViewTubeParam.currentIndex(),
                self.comboBoxInputParam.itemText(index))
        self.panelInputParam.setVisible(False)

    def comboBoxInputParam_TextUpdate(self, text):
        if self.mDataGridViewTubeParam.currentIndex().isValid():
            self.mDataGridViewTubeParam.model().setData(
                self.mDataGridViewTubeParam.currentIndex(),
                text)
        self.panelInputParam.setVisible(False)

    def mDataGridViewTubeParam_CellClick(self, index):
        row = index.row()
        col = index.column()

        cellText = ""
        paramName = ""
        paramInfo = TubeDistributeParamData()
        listValue = []

        self.panelInputParam.setVisible(False)

        if row >= 0:
            self.mDataGridViewTubeParam.setCurrentIndex(index)
            if col == self.Col_ParamValue1:  # Parameter value
                self.AskDataGridViewCellText(self.mDataGridViewTubeParam, row, self.Col_IsReadValue1, cellText)
                if cellText and cellText == "是":
                    self.mDataGridViewTubeParam.setEditTriggers(QTableView.NoEditTriggers)
                else:
                    self.mDataGridViewTubeParam.setEditTriggers(QTableView.AllEditTriggers)

                if not self.mDataGridViewTubeParam.editTriggers() == QTableView.NoEditTriggers:
                    self.comboBoxInputParam.setEditable(False)

                    # Parameter value has dropdown
                    self.AskDataGridViewCellText(self.mDataGridViewTubeParam, row, self.Col_ParamName1, paramName)
                    self.AskInputParamInfoByParamName(paramName, paramInfo)

                    if paramInfo.paramValueType == "2":  # Enumeration
                        for item in paramInfo.Item:
                            listValue.append(item.Value)

                    if listValue:  # Has reference values, show dropdown
                        rect = self.mDataGridViewTubeParam.visualRect(index)

                        # Set dropdown content
                        self.comboBoxInputParam.clear()
                        self.comboBoxInputParam.addItems(listValue)

                        # Set dropdown position
                        self.panelInputParam.setGeometry(rect)

                        # Set dropdown index
                        self.AskDataGridViewCellText(self.mDataGridViewTubeParam, row, col, cellText)
                        self.comboBoxInputParam.setCurrentText(cellText)
                        idx = self.comboBoxInputParam.findText(cellText)
                        if idx >= 0:
                            self.comboBoxInputParam.setCurrentIndex(idx)

                        self.panelInputParam.setVisible(True)

    def AskInputParamInfoByParamName(self, paramName, paramInfo):
        tempParmName = ""
        paramInfo = TubeDistributeParamData()

        if not paramName:
            return -1

        for param in self.m_listInputParam:
            tempParmName = param.paramName
            if tempParmName == paramName:
                paramInfo.CopyData(param)
                break

        return 0

    def qyButtonCalculate_Click(self):
        imagePath = ""
        inputParam = []

        # Get dialog input parameters
        self.AskDialogInputParams(inputParam)
        self.m_listInputParam.clear()
        self.m_listInputParam.extend(inputParam)

        # Calculate
        resp = self.m_mainData.CalculateParams(self.m_listInputParam, self.m_outputParam)
        if not resp:
            return

        # Convert output pipeline coordinate data to row and column grouped point data
        if len(self.m_outputParam.TubesParam) == 2:
            if self.m_outputParam.AllTubesParam and len(self.m_outputParam.AllTubesParam) > 0:
                pass
                # m_mainData.TransTubeParamToPoints(m_outputParam.AllTubesParam[0].ScriptItem, out m_allTubePoints1, 0)
            if self.m_outputParam.AllTubesParam and len(self.m_outputParam.AllTubesParam) > 1:
                pass
                # m_mainData.TransTubeParamToPoints(m_outputParam.AllTubesParam[1].ScriptItem, out m_allTubePoints2, 1)

        # Get corresponding bitmap based on calculation results
        # m_mainData.CalculateImage(m_listInputParam, m_outputParam, out imagePath)

        # Update image
        if imagePath and os.path.exists(imagePath):
            pixmap = QPixmap(imagePath)
            self.scene.clear()
            self.scene.addPixmap(pixmap)

        # Update output parameters
        self.UpdateOutputParams(self.m_outputParam)

        # Update row and column tube count
        self.UpdateTubeCountLines(self.m_outputParam)

        # Update total number of heat exchange tubes
        self.UpdateTubeTotalCount(self.m_outputParam)

        # Set tube layout input parameter intermediate file
        self.m_mainData.SetInputParamsToFile(self.m_listInputParam)

    def AskDialogInputParams(self, listInputParam: List[TubeDistributeParamData]):
        cellText = ""
        listInputParam = []

        for i in range(self.mDataGridViewTubeParam.model().rowCount()):
            paramData1 = TubeDistributeParamData()

            # Parameter ID
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_ParamId1, cellText)
            paramData1.paramId = cellText

            # Reference ID
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_RefId1, cellText)
            paramData1.refParamId = cellText

            # Parameter name
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_ParamName1, cellText)
            paramData1.paramName = cellText

            # Parameter value
            tempParamData = TubeDistributeParamData()
            self.AskInputParamInfoByParamName(paramData1.paramName, tempParamData)
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_ParamValue1, cellText)

            if tempParamData.paramValueType == "2" and cellText:  # Enumeration
                for item in tempParamData.Item:
                    if item.Value == cellText:
                        paramData1.paramValue = item.Key
                        break
            else:
                paramData1.paramValue = cellText

            # Unit
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_ParamUnit1, cellText)
            paramData1.paramUnit = cellText

            # Parameter value type
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_ParamValueType1, cellText)
            paramData1.paramValueType = cellText

            # Reference values
            paramData1.Item = tempParamData.Item.copy()

            # Read-only
            self.AskDataGridViewCellText(self.mDataGridViewTubeParam, i, self.Col_IsReadValue1, cellText)
            paramData1.isReadOnly = cellText

            listInputParam.append(paramData1)

        return 0

    def UpdateOutputParams(self, outputParams: LayoutTubeParam) -> int:
        rowIndex = 0

        self.mDataGridViewOutputParam.model().removeRows(0, self.mDataGridViewOutputParam.model().rowCount())

        # Gasket width
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "垫片宽度")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.Bn))

        # Heat exchange tube spacing
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "换热管间距")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.S))

        # Baffle center distance
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "隔板中心距")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.SN))

        # Baffle cut to tube sheet center line distance
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "折流板切口至管板中心线距离")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.BaffleToODistance))

        # Slideway height
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "滑道高度")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.SlipWayHeight))

        # Channel width perpendicular/parallel to shell fluid flow direction
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "垂直/平行于壳程流体流动方向的通道宽度")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.PassagewayWidth))

        # Baffle outer diameter
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "折流板外径")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.BaffleOD))

        # Tube layout limit circle diameter
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "布管限定圆直径")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.DL))

        # Slideway angle to vertical center line
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "滑道与垂直中心线夹角")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.SlipWayAngle))

        # Slideway thickness
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "滑道厚度")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.SlipWayThick))

        # Bypass baffle thickness
        rowIndex = self.mDataGridViewOutputParam.model().rowCount()
        self.mDataGridViewOutputParam.model().insertRow(rowIndex)
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
            "旁路挡板厚度")
        self.mDataGridViewOutputParam.model().setData(
            self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
            str(outputParams.BPBThick))

        # Bypass baffle heights
        if outputParams.BPBHeights:
            for i in range(len(outputParams.BPBHeights)):
                rowIndex = self.mDataGridViewOutputParam.model().rowCount()
                self.mDataGridViewOutputParam.model().insertRow(rowIndex)
                self.mDataGridViewOutputParam.model().setData(
                    self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamName2),
                    f"旁路挡管高度_{i + 1}")
                self.mDataGridViewOutputParam.model().setData(
                    self.mDataGridViewOutputParam.model().index(rowIndex, self.Col_ParamValue2),
                    str(outputParams.BPBHeights[i]))

        return 0

    def UpdateTubeCountLines(self, outputParams: LayoutTubeParam) -> int:
        rowCnt = 0
        tubeCnt = 0  # Number of pipes in a row
        allTubeCnt = 0  # Number of pipes in a row (all column tubes)
        rowIndex = 0

        self.mDataGridViewTubeCnt.model().removeRows(0, self.mDataGridViewTubeCnt.model().rowCount())
        rowCnt = len(outputParams.CountLines) // 2

        for i in range(rowCnt):
            tubeCnt = outputParams.CountLines[i].Text
            allTubeCnt = len(self.m_allTubePoints1[list(self.m_allTubePoints1.keys())[i]])
            rowIndex = self.mDataGridViewTubeCnt.model().rowCount()
            self.mDataGridViewTubeCnt.model().insertRow(rowIndex)

            self.mDataGridViewTubeCnt.model().setData(
                self.mDataGridViewTubeCnt.model().index(rowIndex, self.Col_No3),
                str(i + 1))

            self.mDataGridViewTubeCnt.model().setData(
                self.mDataGridViewTubeCnt.model().index(rowIndex, self.Col_TubeOriginalCnt3),
                str(allTubeCnt))

            self.mDataGridViewTubeCnt.model().setData(
                self.mDataGridViewTubeCnt.model().index(rowIndex, self.Col_TubeColCnt3),
                str(tubeCnt))

        return 0

    def UpdateTubeTotalCount(self, outputParams: LayoutTubeParam) -> int:
        count = 0

        for countLine in outputParams.CountLines:
            count += countLine.Text

        self.labelTubeTotalCnt.setText(f"换热管总数：{count}")
        return 0

    def mComboBoxTubeBoard_SelectedIndexChanged(self, index):
        # Update heat exchange tube and tube sheet connection content
        self.UpdateTubeBoardConnectData()

    def UpdateTubeBoardConnectData(self) -> int:
        index = 0
        typeText = self.mComboBoxTubeBoard.currentText()

        if not typeText:
            return -1
        # Load bitmap
        self.mListViewTubeBoard.clear()
        # imageList = TubePlantInfo.ImageList()
        # imageList.setColorDepth(QImage.Format.Format_RGB32)
        # imageList.setIconSize(QSize(256, 256))
        self.mListViewTubeBoard.setIconSize(QSize(256, 256))
        self.mListViewTubeBoard.setViewMode(QListView.IconMode)

        while True:
            imagePath = self.GetTubeBoardImagePath(typeText, index + 1)
            if not os.path.exists(imagePath):
                break

            item = QListWidgetItem()
            item.setIcon(QIcon(imagePath))
            self.mListViewTubeBoard.addItem(item)

            # Set selection state
            if index == self.m_tubeBoardData.subtype:
                item.setSelected(True)

            index += 1

        # Set parameters
        self.mTextBoxWeldJoint.setText(self.m_tubeBoardData.weldJoint)
        self.mPanelWeldJoint.setVisible(typeText == "内孔焊")

        return 0

    def mDataGridViewTubeCnt_CellClick(self, index):
        if index.row() >= 0:
            self.m_editTubeCntFlag = True

    def mDataGridViewTubeCnt_CellValueChanged(self, index):
        count = 0
        originCnt = 0
        tempCnt = 0
        cellText = ""
        strNo = ""
        imagePath = ""

        # Determine if this function was triggered by editing the row tube table cell text
        if not self.m_editTubeCntFlag:
            return

        self.m_editTubeCntFlag = False

        if index.row() < 0 or index.column() != self.Col_TubeColCnt3:
            return

        self.AskDataGridViewCellText(self.mDataGridViewTubeCnt, index.row(), self.Col_No3, strNo)
        self.AskDataGridViewCellText(self.mDataGridViewTubeCnt, index.row(), self.Col_TubeColCnt3, cellText)

        if cellText:
            count = int(cellText)

        self.AskDataGridViewCellText(self.mDataGridViewTubeCnt, index.row(), self.Col_TubeOriginalCnt3, cellText)
        if cellText:
            originCnt = int(cellText)

        if count > originCnt:
            QMessageBox.warning(self, "警告", f"第{strNo}行，数量不能大于{originCnt}")
            self.mDataGridViewTubeCnt.model().setData(
                self.mDataGridViewTubeCnt.model().index(index.row(), self.Col_TubeColCnt3),
                str(originCnt))
            return

        tempCnt = originCnt - count
        if tempCnt % 2 != 0:
            QMessageBox.warning(self, "警告", f"第{strNo}行，数量与{originCnt}的差值必须是偶数")
            return

        # Convert row and column grouped point data to output pipeline coordinate data
        if len(self.m_outputParam.TubesParam) == 2:
            tempCnt2 = 0
            key = 0.0
            tubePoints1 = {}  # Upper part pipe coordinates
            tubePoints2 = {}  # Lower part pipe coordinates

            # Update pipe coordinates
            for i in range(len(self.m_allTubePoints1)):
                # Upper part pipe coordinates
                key = list(self.m_allTubePoints1.keys())[i]
                listItem1 = []

                if i == index.row():
                    tempCnt2 = len(self.m_allTubePoints1[key]) - tempCnt
                else:
                    tempCnt2 = len(self.m_allTubePoints1[key])

                for j in range(tempCnt2):
                    listItem1.append(self.m_allTubePoints1[key][j])

                tubePoints1[key] = listItem1

                # Lower part pipe coordinates
                key = list(self.m_allTubePoints2.keys())[i]
                listItem2 = []

                if i == index.row():
                    tempCnt2 = len(self.m_allTubePoints2[key]) - tempCnt
                else:
                    tempCnt2 = len(self.m_allTubePoints2[key])

                for j in range(tempCnt2):
                    listItem2.append(self.m_allTubePoints2[key][j])

                tubePoints2[key] = listItem2

            # Upper part pipe coordinates
            tubeParam1 = []
            # m_mainData.TransPointsToTubeParam(tubePoints1, out tubeParam1)
            self.m_outputParam.TubesParam[0].ScriptItem.clear()
            self.m_outputParam.TubesParam[0].ScriptItem.extend(tubeParam1)

            # Lower part pipe coordinates
            tubeParam2 = []
            # m_mainData.TransPointsToTubeParam(tubePoints2, out tubeParam2)
            self.m_outputParam.TubesParam[1].ScriptItem.clear()
            self.m_outputParam.TubesParam[1].ScriptItem.extend(tubeParam2)

        # Update total number of heat exchange tubes
        self.UpdateTubeTotalCount(self.m_outputParam)

        # Get corresponding bitmap based on calculation results
        # m_mainData.CalculateImage(m_listInputParam, m_outputParam, out imagePath)

        # Update image
        if imagePath and os.path.exists(imagePath):
            pixmap = QPixmap(imagePath)
            self.scene.clear()
            self.scene.addPixmap(pixmap)

    def mOkButton_Click(self):
        # Get dialog output parameters
        self.AskDialogOutputParams(self.m_outputParam)

        # Row and column tube count
        self.AskTubeCountLines(self.m_outputParam)

        # Set tube layout output parameter intermediate file
        self.m_mainData.SetOutputParamsToFile(self.m_outputParam)

        # Get interface tube sheet connection info
        self.AskDialogTubeBoardConnectData(self.m_tubeBoardData)

        # Set tube sheet connection intermediate file
        # m_mainData.SetTubeBoardToFile(m_tubeBoardData)

        self.accept()

    def mCancelButton_Click(self):
        self.reject()

    def AskDialogOutputParams(self, outputParams: LayoutTubeParam) -> int:
        paramName = ""
        paramValue = ""

        outputParams.BPBHeights.clear()

        for i in range(self.mDataGridViewOutputParam.model().rowCount()):
            self.AskDataGridViewCellText(self.mDataGridViewOutputParam, i, self.Col_ParamName2, paramName)
            self.AskDataGridViewCellText(self.mDataGridViewOutputParam, i, self.Col_ParamValue2, paramValue)

            if not paramName:
                continue

            if paramName == "垫片宽度":
                outputParams.Bn = float(paramValue)
            elif paramName == "换热管间距":
                outputParams.S = float(paramValue)
            elif paramName == "隔板中心距":
                outputParams.SN = float(paramValue)
            elif paramName == "折流板切口至管板中心线距离":
                outputParams.BaffleToODistance = float(paramValue)
            elif paramName == "滑道高度":
                outputParams.SlipWayHeight = float(paramValue)
            elif paramName == "垂直/平行于壳程流体流动方向的通道宽度":
                outputParams.PassagewayWidth = int(paramValue)
            elif paramName == "折流板外径":
                outputParams.BaffleOD = float(paramValue)
            elif paramName == "布管限定圆直径":
                outputParams.DL = float(paramValue)
            elif paramName == "滑道与垂直中心夹角":
                outputParams.SlipWayAngle = float(paramValue)
            elif paramName == "滑道厚度":
                outputParams.SlipWayThick = float(paramValue)
            elif paramName == "旁路挡板厚度":
                outputParams.BPBThick = float(paramValue)
            elif "旁路挡管高度" in paramName:
                outputParams.BPBHeights.append(float(paramValue))
        return 0

    def ask_tube_count_lines(self, output_params: LayoutTubeParam) -> int:
        row_cnt = self.table_widget.rowCount()

        for i in range(len(output_params.count_lines)):
            index = i if i < row_cnt else i - row_cnt
            cell_text = self.ask_data_grid_view_cell_text(index, 3)  # 假设“Col_TubeColCnt3”是第4列（索引3）
            try:
                output_params.count_lines[i].text = int(cell_text)
            except ValueError:
                output_params.count_lines[i].text = 0  # 或者报错处理

        return 0

    def ask_dialog_tube_board_connect_data(self) -> TubeBoardConnectData:
        data = TubeBoardConnectData()
        data.type = self.combo_box.currentIndex()

        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).isSelected():
                data.subtype = i
                break

        data.weld_joint = self.line_edit.text()
        return data

    def ask_data_grid_view_cell_text(self, row_index: int, col_index: int) -> str:
        try:
            item = self.table_widget.item(row_index, col_index)
            return item.text() if item else ""
        except:
            return ""

    def get_tube_board_image_path(self, type_text: str, index: int) -> str:
        prj_path = self.ask_project_path()
        if type_text.strip() and prj_path.strip():
            return f"{prj_path}/application/picture/TubeDistribution/{type_text}{index}.png"
        return ""

    def ask_project_path(self) -> str:
        # 模拟 ProjectCore.AskProjectPath(out string prjPath)
        return "/your/project/path"


class TubeBoardConnectData:
    def __init__(self):
        self.type = 0
        self.subtype = 0
        self.weld_joint = ""


class CountLine:
    def __init__(self):
        self.text = 0


class LayoutTubeParam:
    def __init__(self, count=0):
        self.count_lines = [CountLine() for _ in range(count)]



if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = TubeDistributionGUI()
    window.show()

    sys.exit(app.exec_())