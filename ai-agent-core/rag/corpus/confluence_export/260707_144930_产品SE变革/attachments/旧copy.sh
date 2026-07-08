#!/bin/bash
#$1（为廖峥编译生成的中间件拷贝版本）选项release/debug,$2为某一中间件编码,$3为比较标准中间件编码
cd ../tvos_ci_1029
rm -rf tcl
#svn co http://svn04.tclking.com/svn/rtk2851/2851p/branches/P_MP2_RT2851_svn9913_20191029/kernel/android/pie/vendor/tcl
svn co http://svn04.tclking.com/svn/rtk2851/2851p/branches/P_2851_NA_FHD_svn9873_20191028/kernel/android/pie/vendor/tcl
cd  ../tvos_1029

cp -pr $1/release/bin/* ../tvos_ci_1029/tcl/tvos/bin/
#cp -p $1/$1/lib/libsitatv.so ../tvos_ci_1029/tcl/tvos/libGlibc/libsitatv.so
#cp -p $1/$1/lib/libFpiAtsc.so ../tvos_ci_1029/tcl/tvos/libGlibc/libFpiAtsc.so

cp -pr $1/release/lib/* ../tvos_ci_1029/tcl/tvos/lib/
rm -rf $1/release/tvos/lib/*hbbtv*.so
rm -rf $1/release/tvos/lib/libsitatv.so

cp -pr $1/release/jar/* ../tvos_ci_1029/tcl/tvmanager/
rm -rf $1/release/tvmanager/*hbbtv*.jar
cp -p $1/release/lib/libcom_tcl_tv_jni.so ../tvos_ci_1029/tcl/tvmanager/
cp -p $1/release/lib/libsitatv.so ../tvos_ci_1029/tcl/tvmanager/



cp -p $1/release/lib/libhbbtv-server.so ../tvos_ci_1029/tcl/hbbtv/lib/
cp -p $1/release/lib/libhbbtv_plugin.so ../tvos_ci_1029/tcl/hbbtv/lib/plugin/
cp -p $1/release/lib/libcom_tcl_hbbtv_jni.tcl.so ../tvos_ci_1029/tcl/hbbtv/lib/
#rm -rf ../tvos_ci_1029/tcl/hbbtv/lib/libcom_tcl_hbbtv_jni.so

cp -p $1/release/lib/libalexa.so ../tvos_ci_1029/tcl/alexa/lib/
cp -p $1/release/lib/libAlexaJni.so ../tvos_ci_1029/tcl/alexa/lib/

cp -p $1/release/jar/com.tcl.hbbtv.jar ../tvos_ci_1029/tcl/hbbtv/framework/
#cp -pr $1/$1/res/hbbtv_config/* ../tvos_ci_1029/tcl/hbbtv/etc/hbbtv/
#cp -pr $1/$1/res/rtk2851/hbbtv_config/* ../tvos_ci_1029/tcl/hbbtv/etc/hbbtv/


#copy apk
##cp -pr $1/app/* ../tvos_ci_1029/tcl/tvos/app/
cp -pr $1/release/res/hbbtv_config/* ../tvos_ci_1029/tcl/hbbtv/etc/hbbtv/	
cp -pr $1/release/app/* ../tvos_ci_1029/tcl/am_apps/
cp -pr $1/release/res/rtk2851/hbbtv_config/* ../tvos_ci_1029/tcl/hbbtv/etc/hbbtv/
cp -pr $1/release/res/rtk2851/crt ../tvos_ci_1029/tcl/persist/
cp -pr $1/release/res/rtk2851/ua ../tvos_ci_1029/tcl/persist/	
cp -pr $1/release/res/rtk2851/etc ../tvos_ci_1029/tcl/tvos/	
cp -pr $1/tbrowser2/libs/* ../tvos_ci_1029/tcl/tbrowser2/lib/
cp -pr $1/tbrowser2/res/* ../tvos_ci_1029/tcl/tbrowser2/etc/tbrowser2/
cp -pr $1/tbrowser2/jar/* ../tvos_ci_1029/tcl/tbrowser2/framework/
rm -rf $1/tbrowser2/framework/tbrowser.jar
cp -p $1/tbrowser2/libjsext_tutil.so ../tvos_ci_1029/tcl/tbrowser2/lib/

cp -pr $1/AlexaService/* ../tvos_ci_1029/tcl/alexa/lib/
#cp -pr $1/release/lib/* ../tvos_ci_1029/tcl/alexa/lib/
#cp -p $tvos_path/$1/lib/libalexa.so $src_tvos_path/alexa/lib/
#cp -p $tvos_path/$1/lib/libAlexaJni.so $src_tvos_path/alexa/lib/

cp -pr $1/OPTEE/libCiPlusCCECP.so ../tvos_ci_1029/tcl/tvos/lib
cp -pr $1/OPTEE/libCiplusTA.a ../tvos_ci_1029/tcl/optee/ci_ecp
cp -pr $1/OPTEE/res/* ../tvos_ci_1029/tcl/optee/ci_ecp/res

cp -pr $1/release/lib/libCiPlusCCECP.so ../tvos_ci_1029/tcl/tvos/lib
cp -pr $1/release/tee/rtk2851m/ci_ecp/libCiplusTA.a ../tvos_ci_1029/tcl/optee/ci_ecp
cp -pr $1/release/tee/rtk2851m/ci_ecp/res/* ../tvos_ci_1029/tcl/optee/ci_ecp/res

cp -p $1/release/Bsp_info.txt ../tvos_ci_1029/tcl/tvos/Bsp_info.txt
cp -p $1/release/fpp_info.txt ../tvos_ci_1029/tcl/tvos/fpp_info.txt
cp -p $1/release/tbrowser2.0_info.txt ../tvos_ci_1029/tcl/tbrowser2/tbrowser2.0_info.txt
cp -p $1/release/svninfo.txt ../tvos_ci_1029/tcl//svninfo.txt
#cp -p $1/tbrowser2.0_info.txt ../tvos_ci_1029/tcl/tvos/tbrowser2/tbrowser2.0_info.txt
#cp -p $1/tbrowser_info.txt ../tvos_ci_1029/tcl/tvos/tbrowser2/tbrowser_info.txt

cp -p $1/fpp/libfpp.so ../tvos_ci_1029/tcl/tvos/lib/
cp -p $1/fpp/libtcl_memc.so ../tvos_ci_1029/tcl/tvmanager/

cp -p $1/webview/TCLWebView.apk ../tvos_ci_1029/tcl/webview/
cp -p $1/webview/twebview.jar ../tvos_ci_1029/tcl/webview/

#cp -pr $1/system/apps/* ../tvos_ci_1029/tcl/sita/apps/

   
svn st

