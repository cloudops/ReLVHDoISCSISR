Summary: LVHDoISCSISR with SR resigning
Name: ReLVHDoISCSISR
Version: %{?version}%{!?version:1.0}
Release: %{?release}%{!?release:1}
License: GPL
Group: Applications/System
Source: %{name}-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot

%description
Enables the resigning of a new LVHDoISCSISR if it is logically identical to an exists SR.  Useful for introducing a SAN snapshot.

%prep
%setup -q -n %{name}-%{version}

%build
:

%install
rm -rf $RPM_BUILD_ROOT
find . -type f | cpio -pdm $RPM_BUILD_ROOT
find . -path \*filelist -prune -type f -o -type f -print | sed -e 's#^./#/#' >filelist

%clean
rm -rf $RPM_BUILD_ROOT

%files -f filelist

%post

cd /opt/xensource/sm/; ln -sf "ReLVHDoISCSISR.py" "ReLVMoISCSISR"
cd /opt/xensource/sm/; ln -sf "VDILUNSR.py" "VDILUNSR"

%changelog
