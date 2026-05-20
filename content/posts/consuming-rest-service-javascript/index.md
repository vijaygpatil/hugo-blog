---
title: "Consuming REST Service with JavaScript"
date: 2018-06-22
draft: false
tags: ["javascript", "jquery", "rest", "ajax", "frontend"]
description: "How to consume REST APIs from front-end JavaScript using jQuery's AJAX functionality — a practical template with the options you'll actually use, and what each one does."
---

For consuming REST Services using front-end JavaScript frameworks, we recommend using jQuery. jQuery has a robust AJAX functionality built for making REST Service calls. We recommend jQuery version 1.5 (ideally 1.7) or higher.

Here is a sample template for making service calls using AJAX in jQuery. There are more options in `jQuery.ajax` than what are listed below — you can use them based on your needs.

## Sample jQuery.ajax Template

```javascript
$.ajax({
    // The type of request to make ("POST" or "GET"), default is "GET"
    type: "GET",

    // The URL to send the request to
    url: "https://api.example.com/expenses",

    // Data to send with the request (for POST/PUT)
    data: {},

    // The type of data you're expecting back from the server
    dataType: "json",

    // Content type of the request body (important for POST with JSON)
    contentType: "application/json; charset=utf-8",

    // HTTP headers to include with the request
    headers: {
        "Authorization": "Bearer " + authToken,
        "Accept": "application/json"
    },

    // Called when the request succeeds
    success: function(data, textStatus, jqXHR) {
        console.log("Response:", data);
    },

    // Called when the request fails
    error: function(jqXHR, textStatus, errorThrown) {
        console.error("Request failed:", textStatus, errorThrown);
    },

    // Called when the request completes, whether success or failure
    complete: function(jqXHR, textStatus) {
        console.log("Request complete:", textStatus);
    }
});
```

## GET Request — Fetching a Resource

The simplest case: fetching data from a REST endpoint.

```javascript
$.ajax({
    type: "GET",
    url: "https://api.example.com/expenses/12345",
    dataType: "json",
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    },
    success: function(expense) {
        displayExpense(expense);
    },
    error: function(jqXHR, textStatus, errorThrown) {
        if (jqXHR.status === 404) {
            showMessage("Expense not found.");
        } else {
            showMessage("Failed to load expense: " + errorThrown);
        }
    }
});
```

You can also use the shorthand `$.getJSON()` for simple GET requests that return JSON:

```javascript
$.getJSON("https://api.example.com/expenses/12345", function(expense) {
    displayExpense(expense);
});
```

## POST Request — Creating a Resource

When sending JSON in the request body, set `contentType` to `application/json` and stringify the data object manually:

```javascript
var newExpense = {
    reportId: "RPT-001",
    amount: 45.50,
    currencyCode: "USD",
    description: "Team lunch",
    expenseDate: "2018-06-20"
};

$.ajax({
    type: "POST",
    url: "https://api.example.com/expenses",
    contentType: "application/json; charset=utf-8",
    dataType: "json",
    data: JSON.stringify(newExpense),
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    },
    success: function(createdExpense) {
        console.log("Created expense with ID:", createdExpense.id);
        redirectToExpense(createdExpense.id);
    },
    error: function(jqXHR, textStatus, errorThrown) {
        var response = jqXHR.responseJSON;
        if (response && response.message) {
            showError(response.message);
        } else {
            showError("Failed to create expense.");
        }
    }
});
```

A common mistake here: omitting `JSON.stringify()` and passing the object directly to `data`. Without it, jQuery serialises the object as form-encoded key=value pairs, not JSON, and the server will reject it or misparse the body.

## PUT Request — Updating a Resource

```javascript
var updatedExpense = {
    amount: 52.00,
    description: "Team lunch (updated)"
};

$.ajax({
    type: "PUT",
    url: "https://api.example.com/expenses/" + expenseId,
    contentType: "application/json; charset=utf-8",
    dataType: "json",
    data: JSON.stringify(updatedExpense),
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    },
    success: function(expense) {
        showMessage("Expense updated.");
    },
    error: function(jqXHR) {
        showError("Update failed: " + jqXHR.status);
    }
});
```

## DELETE Request

```javascript
$.ajax({
    type: "DELETE",
    url: "https://api.example.com/expenses/" + expenseId,
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    },
    success: function() {
        removeExpenseFromList(expenseId);
    },
    error: function(jqXHR) {
        showError("Delete failed: " + jqXHR.status);
    }
});
```

## Using Promises (Deferred)

`$.ajax()` returns a jqXHR object that implements jQuery's Deferred interface. You can chain `.done()`, `.fail()`, and `.always()` instead of passing callbacks in the options object:

```javascript
var request = $.ajax({
    type: "GET",
    url: "https://api.example.com/expenses",
    dataType: "json",
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    }
});

request.done(function(expenses) {
    renderExpenseList(expenses);
});

request.fail(function(jqXHR, textStatus) {
    showError("Could not load expenses: " + textStatus);
});

request.always(function() {
    hideLoadingSpinner();
});
```

This style separates the request definition from the response handling, which is useful when you want to pass the request object around or attach multiple handlers.

## Setting Defaults for All Requests

If you're making many calls to the same API, use `$.ajaxSetup()` to define defaults once so you don't repeat them everywhere:

```javascript
$.ajaxSetup({
    contentType: "application/json; charset=utf-8",
    dataType: "json",
    headers: {
        "Authorization": "Bearer " + getAuthToken()
    },
    error: function(jqXHR, textStatus, errorThrown) {
        if (jqXHR.status === 401) {
            redirectToLogin();
        }
    }
});
```

After this, individual `$.ajax()` calls only need to specify what differs — `type`, `url`, `data`, and the `success` callback.

## Handling CORS

If your JavaScript is served from a different origin than your REST API, the browser enforces Cross-Origin Resource Sharing (CORS) rules. The server needs to respond with the right headers (`Access-Control-Allow-Origin`, etc.) — this is a server-side concern, not something jQuery controls.

On the client side, for cross-origin requests that use non-standard headers or methods other than GET/POST, the browser sends a preflight `OPTIONS` request first. You don't need to handle this manually; the browser does it. What you do need to make sure is that your server responds to `OPTIONS` requests correctly.

If you're seeing requests blocked with "has been blocked by CORS policy" in the browser console, the fix is on the server, not in your jQuery code.

## A Note on jQuery Version

As mentioned, jQuery 1.7 or higher is recommended. The Deferred/Promise interface was significantly improved in 1.5 and stabilised by 1.7. If you're on an older version, `.done()` and `.fail()` may not behave as documented above.

jQuery 2.x dropped support for IE 6/7/8. If you need to support those browsers, stay on the 1.x line. If you don't — and in 2018, you probably shouldn't — jQuery 2.x or 3.x is the better choice.

---

The patterns above cover the majority of REST consumption scenarios you'll encounter. For more advanced use cases — request cancellation, upload progress events, JSONP — refer to the [jQuery.ajax documentation](https://api.jquery.com/jquery.ajax/).
