using System;
using System.Collections.Generic;
using System.Xml;
using Newtonsoft.Json;

namespace StrengthInterfaceDll
{
    public class CalPartInterface
    {
        public string IntergratedEquipment(string inputJson)
        {
            var input = JsonConvert.DeserializeObject<InputInterfaceDatas>(inputJson);
            var output = new OutputInterfaceDatas
            {
                Logs = new List<string> { "执行成功", $"项目：{input.ProjectName}" }
            };
            return JsonConvert.SerializeObject(output, Newtonsoft.Json.Formatting.Indented);
        }
    }

    public class InputInterfaceDatas
    {
        public InputInterfaceDatas()
        {
            DictPart = new Dictionary<string, string>();
            DictDatas = new Dictionary<string, Dictionary<string, string>>();
        }

        public string ProjectName { get; set; }
        public string ExchangerType { get; set; }
        public List<WorkCondition> WSList { get; set; }
        public Dictionary<string, TubeOpenTable> TTDict { get; set; }
        public Dictionary<string, string> DesignParams { get; set; }
        public Dictionary<string, string> DictPart { get; set; }
        public Dictionary<string, Dictionary<string, string>> DictDatas { get; set; }
    }

    public class WorkCondition
    {
        public string TubeWorkingPressure { get; set; }
        public string TubeWorkingTemperature { get; set; }
        public string ShellWorkingPressure { get; set; }
        public string ShellWorkingTemperature { get; set; }
    }

    public class TubeOpenTable
    {
        public int ttNo { get; set; }
        public string ttCode { get; set; }
        public string ttUse { get; set; }
        public string ttDN { get; set; }
        public string ttPClass { get; set; }
        public string ttType { get; set; }
        public string ttRF { get; set; }
        public string ttSpec { get; set; }
        public string ttAttach { get; set; }
        public string ttPlace { get; set; }
        public string ttLoc { get; set; }
        public string ttFW { get; set; }
        public string ttThita { get; set; }
        public string ttAngel { get; set; }
        public string ttH { get; set; }
        public string ttMemo { get; set; }
    }

    public class OutputInterfaceDatas
    {
        public OutputInterfaceDatas()
        {
            Logs = new List<string>();
            DictOutDatas = new Dictionary<string, ResultInfo2>();
        }

        public List<string> Logs { get; set; }
        public Dictionary<string, ResultInfo2> DictOutDatas { get; set; }
    }

    public class ResultInfo2
    {
        public ResultInfo2()
        {
            IsSuccess = false;
            Datas = new List<BaseDataInfo>();
        }

        public bool IsSuccess { get; set; }
        public List<BaseDataInfo> Datas { get; set; }
    }

    public class BaseDataInfo
    {
        public string Key { get; set; }
        public string Value { get; set; }
    }
}
