$(document).ready(function() {
    $('#scan-form').on('submit', function(e) {
        e.preventDefault();
        const url = $('#url-input').val();

        // Update button state to show loading
        $('#btn-text').hide();
        $('#btn-spinner').show();
        $('#analyze-btn').prop('disabled', true);

        $.ajax({
            type: 'POST',
            url: '/start_scan',
            data: { url: url },
            success: function(response) {
                // Redirect to the results page for the new scan
                window.location.href = '/scan/' + response.scan_id;
            },
            error: function() {
                alert('An error occurred. Please try again.');
                // Restore button state
                $('#btn-text').show();
                $('#btn-spinner').hide();
                $('#analyze-btn').prop('disabled', false);
            }
        });
    });
});