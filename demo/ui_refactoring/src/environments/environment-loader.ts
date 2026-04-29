import { environment as defaultEnvironment } from './environment';

export const EnvironmentLoader = new Promise<any>((resolve, reject) => {
  let url = './config/app.json';

  if (defaultEnvironment.production) {
    url = './config/app.prod.json';
  }

  const xmlhttp = new XMLHttpRequest(),
    method = 'GET';

  xmlhttp.open(method, url, true);
  xmlhttp.onload = function () {
    if (xmlhttp.status === 200) {
      resolve(JSON.parse(xmlhttp.responseText));
    } else {
      resolve(defaultEnvironment);
    }
  };
  xmlhttp.send();
});
