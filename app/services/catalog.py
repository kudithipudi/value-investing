"""Catalog of known Graham & Doddsville newsletter issues and discovery of new ones.

The Columbia listing page (business.columbia.edu/.../graham-and-doddsville-newsletter)
returns 403 to non-browser clients, but individual PDFs are downloadable. The canonical
catalog below was captured from that listing page. New issues are discovered by scanning
the public grahamanddoddsville.net archive mirror plus manual URL entry (see
app/services/discovery.py).
"""

# (season, issue_number, title, url)
KNOWN_ISSUES: list[tuple[str, int | None, str, str]] = [
    ("Spring 2026", 52, "Spring 2026", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Spring%202026%20Issue%20(Master)_05192026_vF2.pdf"),
    ("Fall 2025", 51, "Fall 2025", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham_Doddsville_Fall_2025_Issue_vfPrint_0.pdf"),
    ("Spring 2025", 50, "Spring 2025", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham_Doddsville_Spring_2025_Issue_.pdf"),
    ("Fall 2024", 50, "Fall 2024 (50th edition)", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Fall%202024%20Issue%20(Master)_120224_vF.pdf"),
    ("Spring 2024", 49, "Spring 2024", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Spring%202024%20Issue%20FINAL.pdf"),
    ("Fall 2023", 48, "Fall 2023", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Fall%202023%20Issue%20FINAL.pdf"),
    ("Spring 2023", 47, "Spring 2023", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Spring%202023%20Issue%20vFINAL%20(2023.04.27).pdf"),
    ("Fall 2022", 46, "Fall 2022", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20Doddsville%20Fall%202022%20Issue%2046_0.pdf"),
    ("Spring 2022", 45, "Spring 2022", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2045_1.pdf"),
    ("Fall 2021", 43, "Fall 2021", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2043_vF.pdf"),
    ("Spring 2021", 42, "Spring 2021", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2042_v8.pdf"),
    ("Winter 2021", 41, "Winter 2021", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2041_v15.pdf"),
    ("Fall 2020", 40, "Fall 2020", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2040_v19.pdf"),
    ("Spring 2020", 39, "Spring 2020", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2039_v13_FINAL.pdf"),
    ("Winter 2020", 38, "Winter 2020", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/GD_38_vf.pdf"),
    ("Fall 2019", 37, "Fall 2019", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%26Doddsville_Issue37.pdf"),
    ("Spring 2019", 36, "Spring 2019", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2036_vF.pdf"),
    ("Winter 2019", 35, "Winter 2019", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2035_vPrint.pdf"),
    ("Fall 2018", 34, "Fall 2018", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2034_v22.pdf"),
    ("Spring 2018", 33, "Spring 2018", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2033_v24.pdf"),
    ("Winter 2018", 32, "Winter 2018", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2032_vFF%2025-Jan%20HARD.pdf"),
    ("Fall 2017", 31, "Fall 2017", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2031_vF.pdf"),
    ("Spring 2017", 30, "Spring 2017", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2030_Spring%202017%20-%20v4.pdf"),
    ("Winter 2017", 29, "Winter 2017", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2029_small_0.pdf"),
    ("Fall 2016", 28, "Fall 2016", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2028_Fall2016.pdf"),
    ("Spring 2016", 27, "Spring 2016", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2027.pdf"),
    ("Winter 2016", 26, "Winter 2016", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue_26.pdf"),
    ("Fall 2015", 25, "Fall 2015", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2025_0.pdf"),
    ("Spring 2015", 24, "Spring 2015", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2024.pdf"),
    ("Winter 2015", 23, "Winter 2015", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville_Issue%2023_Final.pdf"),
    ("Fall 2014", 22, "Fall 2014", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville_Issue%2022_Fall%202014_1.pdf"),
    ("Spring 2014", 21, "Spring 2014", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2021%20-%20Spring%202014.pdf"),
    ("Winter 2014", 20, "Winter 2014", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2020%20-%20Winter%202014.pdf"),
    ("Fall 2013", 19, "Fall 2013", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2019%20-%20Fall%202013.pdf"),
    ("Spring 2013", 18, "Spring 2013", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2018%20-%20Spring%202013_0.pdf"),
    ("Winter 2013", 17, "Winter 2013", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2017%20-%20Winter%202013.pdf"),
    ("Fall 2012", 16, "Fall 2012", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2016%20-%20Fall%202012_vFINAL2.pdf"),
    ("Spring 2012", 15, "Spring 2012", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2015%20-%20Spring%202012.pdf"),
    ("Winter 2012", 14, "Winter 2012", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%26%20Doddsville%20-%20Issue%2014%20-%20Winter%202012.pdf"),
    ("Fall 2011", 13, "Fall 2011", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20%20Doddsville%20-%20Issue%2013%20-%20Fall%202011%20-%20v2.pdf"),
    ("Winter 2011", 11, "Winter 2011", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/GDNewsletterWinter2011.pdf"),
    ("Fall 2010", 10, "Fall 2010", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Newsletter%20Issue%2010_Fall2010_v4.pdf"),
    ("Winter 2010", 8, "Winter 2010", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Winter2010.pdf"),
    ("Fall 2009", 7, "Fall 2009", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20and%20Doddsville-%20Issue%207%20Fall%202009.pdf"),
    ("Summer 2009", 6, "Summer 2009", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20and%20Doddsville-%20Issue%206%20Summer%202009.pdf"),
    ("Winter 2009", 5, "Winter 2009", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20and%20Doddsville%20-%20Issue%205%20Winter%202009.pdf"),
    ("Summer/Fall 2008", 4, "Summer/Fall 2008", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20And%20Doddsville%20-%20Issue%204%20Summer%202008.pdf"),
    ("Winter 2007/2008", 3, "Winter 2007/2008", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/GrahamandDoddsville_winter_2008_final.pdf"),
    ("Summer 2007", 2, "Summer 2007", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20and%20Doddsville%20-%20Issue%202_Summer%202007.pdf"),
    ("Winter 2006", 1, "Winter 2006/2007", "https://business.columbia.edu/sites/default/files-efs/imce-uploads/Graham%20and%20Doddsville%20-%20Issue%201_December%202006.pdf"),
]

CATALOG: dict[str, dict] = {
    url: {"season": season, "issue_number": num, "title": title}
    for season, num, title, url in KNOWN_ISSUES
}
